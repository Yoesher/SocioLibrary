import json

import pytest
from fastapi.testclient import TestClient

from sociolit import appearance, graph
from sociolit.ai_context import TASKS, AIWorkspace, fingerprint
from sociolit.crosslanguage import expand, search
from sociolit.indexing import import_snapshot
from sociolit.preferences import save_preferences
from sociolit.server import create_app
from sociolit.service import refresh_after_sync
from sociolit.store import Store
from sociolit.zotero import Snapshot


@pytest.fixture
def library(tmp_path):
    store = Store(tmp_path)
    items = [
        {'key': 'A', 'title': 'Fertility intentions and childcare', 'abstract': 'Fertility intentions depend on care.',
         'authors': ['English Author'], 'year': 2024, 'tags': ['care'], 'doi': '10.1/example'},
        {'key': 'B', 'title': '家庭照料与生育意愿', 'abstract': '家庭照料支持。', 'tags': ['care'], 'year': 2025},
        {'key': 'C', 'title': 'Motherhood penalty and employment', 'abstract': 'A wage penalty for motherhood.', 'tags': []},
    ]
    import_snapshot(store, Snapshot('zotero:test', items, [], True))
    create_app(store, {})
    return store


def test_chinese_finds_english_without_model_and_explains_coverage(library):
    def unavailable():
        raise RuntimeError('Local model missing')
    rows, info = search(library, '生育意愿', None, unavailable)
    assert any(row['item_id'] == 'zotero:test:A' for row in rows)
    assert not info['semantic'] and 'Local model missing' in info['message']
    assert 'fertility intentions' in info['expanded_queries']


def test_english_expands_to_chinese_and_longest_phrase_wins(library):
    assert '生育意愿' in expand('fertility intentions')
    assert 'motherhood penalty' in expand('母职惩罚')
    assert expand('生育支持政策') == ['fertility support', 'family policy', 'parental leave']
    assert not expand('familyx')
    assert len(expand('生育 女性 就业 教育 家庭')) <= 8


def test_smart_search_combines_semantics_and_filters(library):
    first = library.search('fertility')[0]
    rows, info = search(library, '生育意愿', ['zotero:test:A'], lambda: ([first], '核心试点'))
    assert info['semantic'] and info['semantic_scope'] == '核心试点'
    assert all(row['item_id'] == 'zotero:test:A' for row in rows)


def test_smart_api_keeps_filters_and_legacy_response(library):
    with TestClient(create_app(library, {}), base_url='http://localhost') as client:
        headers = {'X-Sociolit-Token': client.get('/api/status').json()['token']}
        result = client.post('/api/search', headers=headers, json={'query':'生育意愿','mode':'auto','year':'2024'}).json()
        assert result['results'] and all(row['year'] == '2024' for row in result['results'])
        assert result['search_info']['expanded_queries']
        assert isinstance(client.post('/api/search', headers=headers, json={'query':'fertility'}).json(), list)
        assert client.post('/api/search', headers=headers, json={'query':'生育','mode':'auto','year':'1900'}).json()['results'] == []
        assert client.post('/api/search', json={'query':'生育','mode':'auto'}).status_code == 403


def test_graph_shared_tags_are_explained_not_citations(library):
    value = graph.build(library, seed='zotero:test:A')
    assert len(value['nodes']) == 2
    assert any(e['origin'] == 'tags' and e['label'] == '共享标签：care' for e in value['edges'])
    assert not any(e.get('kind') == 'cites' for e in value['edges'])
    assert not graph.build(library, seed='zotero:test:A', include_auto=False)['edges']


def test_manual_links_survive_source_deletion_and_have_direction(library):
    record = graph.create_link(library, 'zotero:test:A', 'zotero:test:B', 'cites', '核对第2页')
    with library.connect() as db:
        db.execute("DELETE FROM items WHERE id='zotero:test:B'")
    value = graph.build(library, seed='zotero:test:A', include_auto=False)
    assert any(not n['current'] and n['title'] == '家庭照料与生育意愿' for n in value['nodes'])
    edge = value['edges'][0]
    assert edge['source'] == 'zotero:test:A' and edge['target'] == 'zotero:test:B'
    assert edge['id'] == record['id'] and edge['note'] == '核对第2页'
    assert 'path' not in json.dumps(value)


def test_graph_archive_restore_revision_and_duplicate_guard(library):
    record = graph.create_link(library, 'zotero:test:B', 'zotero:test:A', 'related', '线索')
    with pytest.raises(ValueError):
        graph.create_link(library, 'zotero:test:A', 'zotero:test:B', 'related', '重复')
    graph.archive(library, record['id'], record['revision'], True)
    assert not graph.build(library, seed='zotero:test:A', include_auto=False)['edges']
    archived = graph.build(library, seed='zotero:test:A', include_auto=False, include_archived=True)['edges'][0]
    with pytest.raises(ValueError):
        graph.archive(library, record['id'], record['revision'], False)
    graph.archive(library, record['id'], archived['revision'], False)
    assert graph.build(library, seed='zotero:test:A', include_auto=False)['edges']


@pytest.mark.parametrize('source,target,kind', [('A','A','related'),('A','B','made-up'),('A','missing','related')])
def test_invalid_links_never_persist(library, source, target, kind):
    with pytest.raises(ValueError):
        graph.create_link(library, 'zotero:test:'+source, 'zotero:test:'+target, kind, '')
    with library.connect() as db:
        assert db.execute('SELECT count(*) FROM literature_links').fetchone()[0] == 0


def test_graph_bounds_and_empty_query(library):
    assert len(graph.catalog(library, 'Fertility')) == 1
    assert graph.build(library, query='不存在')['nodes'] == []
    for limit in (1,81):
        with pytest.raises(ValueError):
            graph.build(library, limit=limit)


def test_duplicates_are_candidates_only(library):
    import_snapshot(library, Snapshot('journals:synthetic', [{'key':'D','title':'A different title','doi':'10.1/example','tags':[]}], [], True))
    before = library.stats()
    duplicates = graph.duplicates(library)
    assert duplicates['total'] == 1 and duplicates['groups'][0]['reason'] == '相同 DOI'
    assert library.stats() == before


def test_appearance_and_existing_preferences_preserve_each_other(library, tmp_path):
    save_preferences({}, tmp_path, [str(tmp_path)], ['生育'])
    value = {'theme':'ink','motion':'none','density':'compact','auto_embed':False}
    appearance.save(tmp_path,value)
    save_preferences({},tmp_path,[str(tmp_path)],['生育','婚育'])
    assert appearance.read(tmp_path) == {**value, 'design': 'apple'}
    assert json.loads((tmp_path/'preferences.json').read_text(encoding='utf-8'))['collection_keywords'] == ['生育','婚育']


@pytest.mark.parametrize('key,value',[('design','invalid'),('theme','invalid'),('motion','bounce'),('density','giant'),('auto_embed','yes')])
def test_bad_preferences_do_not_replace_file(library, key, value):
    appearance.save(library.directory, appearance.DEFAULTS)
    previous = (library.directory/'preferences.json').read_bytes()
    bad = {**appearance.DEFAULTS, key:value}
    with pytest.raises(ValueError):
        appearance.save(library.directory,bad)
    assert (library.directory/'preferences.json').read_bytes() == previous


def test_legacy_appearance_defaults_without_rewriting_private_preferences(tmp_path):
    path = tmp_path / 'preferences.json'
    path.write_text(json.dumps({'collection_keywords': ['生育'], 'theme': 'ink', 'custom': 42}))
    before = path.read_bytes()
    assert appearance.read(tmp_path) == {**appearance.DEFAULTS, 'theme': 'ink'}
    assert path.read_bytes() == before


@pytest.mark.parametrize('design', ['apple', 'fluent', 'material'])
def test_design_roundtrip_and_legacy_api_preserve_other_settings(library, design):
    save_preferences({}, library.directory, [str(library.directory)], ['生育'])
    with TestClient(create_app(library, {}), base_url='http://localhost') as client:
        headers = {'X-Sociolit-Token': client.get('/api/status').json()['token']}
        value = {**appearance.DEFAULTS, 'design': design, 'auto_embed': False}
        assert client.post('/api/appearance', headers=headers, json=value).json() == value
        # A previous-version client has no design field. It must not reset it.
        old = {key: val for key, val in value.items() if key != 'design'}
        old['theme'] = 'ink'
        result = client.post('/api/appearance', headers=headers, json=old)
        assert result.status_code == 200 and result.json()['design'] == design
        assert client.get('/api/appearance', headers=headers).json() == {**value, 'theme': 'ink'}
    prefs = json.loads((library.directory / 'preferences.json').read_text(encoding='utf-8'))
    assert prefs['collection_keywords'] == ['生育']
    assert prefs['pdf_roots'] == [str(library.directory)]


def test_workbench_routes_require_authorization_and_origin(library):
    with TestClient(create_app(library,{}),base_url='http://localhost') as client:
        for path in ['/api/appearance','/api/maintenance','/api/literature/catalog']:
            assert client.get(path).status_code == 403
        headers={'X-Sociolit-Token':client.get('/api/status').json()['token']}
        assert client.post('/api/graph',json={},headers=headers).status_code == 200
        assert client.post('/api/appearance',json=appearance.DEFAULTS,headers={**headers,'Origin':'https://evil.example'}).status_code == 403
        assert client.post('/api/appearance',json={**appearance.DEFAULTS,'theme':'rose'},headers=headers).status_code == 200
        assert client.get('/api/appearance',headers=headers).json()['theme'] == 'rose'
        assert client.get('/api/maintenance',headers=headers).json()['last_import']['items_changed'] == 3


def test_workflow_never_downloads_or_automatically_indexes_whole_library(library, tmp_path):
    calls=[]
    result=refresh_after_sync(library,{}, {'items_changed':1,'warnings':['private warning']}, lambda:calls.append(1), tmp_path)
    assert not calls and 'semantic' not in result['workflow']
    assert 'private warning' not in json.dumps(library.state('workflow_summary'))


def test_workflow_only_extends_established_pilot_and_surfaces_failure(library, tmp_path, monkeypatch):
    library.set_state('semantic_scope',{'item_ids':['zotero:test:A']})
    (tmp_path/'sociolit-model.json').write_text('{}')
    monkeypatch.setattr('sociolit.service.build_configured_embeddings',lambda *_args,**_kw:{'indexed':2})
    config={'semantic':{'collection_keywords':['生育']}}
    result=refresh_after_sync(library,config,{'items_changed':1},lambda:object(),tmp_path)
    assert result['workflow']['semantic']['indexed'] == 2
    def fail(*_,**__):
        raise RuntimeError('synthetic failure')
    monkeypatch.setattr('sociolit.service.build_configured_embeddings',fail)
    result=refresh_after_sync(library,config,{'items_changed':1},lambda:object(),tmp_path)
    assert 'synthetic failure' in result['workflow']['message'] and result['items_changed'] == 1
    appearance.save(library.directory,{**appearance.DEFAULTS,'auto_embed':False})
    result=refresh_after_sync(library,config,{},lambda:pytest.fail('Must not load model'),tmp_path)
    assert 'semantic' not in result['workflow']


def test_organize_task_uses_existing_preview_boundary_without_network(library):
    assert 'organize' in TASKS
    class Profiles:
        def get(self, _):
            return {'id':'a'*32,'name':'Synthetic','model':'test','protocol':'responses','base_url':'https://api.openai.com/v1','max_output_tokens':1000}
    workspace=AIWorkspace(library,Profiles())
    with library.connect() as db:
        row=db.execute('SELECT * FROM chunks LIMIT 1').fetchone()
    # profile_revision uses only persisted settings; no key or request is needed.
    preview=workspace.prepare('a'*32,'请整理主题和方法','organize',[{'chunk_id':row['id'],'digest':fingerprint(row)}])
    assert '待核对建议' in preview['prompt'] and '材料未提供' in preview['prompt']


def test_attachment_index_is_used(library):
    with library.connect() as db:
        plans = db.execute('EXPLAIN QUERY PLAN SELECT id FROM chunks WHERE file_id=?',('file',)).fetchall()
        assert any('chunks_file_idx' in row[3] for row in plans)
