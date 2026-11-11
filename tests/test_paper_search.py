import json
from hashlib import sha256
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sociolit.desktop import DesktopAPI
from sociolit.literature import recommend_metadata
from sociolit.paper_search import abstract_from_pages, backmatter, fingerprint, lexical
from sociolit.server import create_app
from sociolit.source_links import locate
from sociolit.store import Store


@pytest.fixture
def library(tmp_path):
    store = Store(tmp_path)
    source = 'zotero:synthetic'
    with store.connect() as db:
        for n in range(24):
            key = f'P{n:07d}'
            identity = source + ':' + key
            meta = {'authors': ['Synthetic'], 'year': 2024, 'abstract': '研究生育支持与家庭照料。', 'journal': 'Synthetic Journal'}
            db.execute('INSERT INTO items VALUES(?,?,?,?,?,?,?)',
                       (identity, source, key, f'生育支持研究 {n}', 'journalArticle', json.dumps(meta), str(n)))
            file = source + ':' + f'F{n:07d}'
            db.execute('INSERT INTO files VALUES(?,?,?,?,?,?)', (file, identity, 'synthetic.pdf', 'hash', 'indexed', ''))
            store.add_chunk(db, item_id=identity, text='生育支持研究\n研究生育支持与家庭照料。', kind='metadata')
            store.add_chunk(db, item_id=identity, file_id=file, page=2, page_label='102',
                            text='生育支持政策的研究考察家庭照料与生育决策之间的关系。', kind='pdf')
            store.add_chunk(db, item_id=identity, file_id=file, page=23, page_label='123',
                            text='参考文献\n生育支持\n作者单位：合成机构\n责任编辑：合成编辑', kind='pdf')
    app = create_app(store, {})
    with TestClient(app, base_url='http://localhost') as client:
        headers = {'X-Sociolit-Token': client.get('/api/status').json()['token']}
        yield store, client, headers


def test_all_matching_papers_are_paginated_without_overlap(library):
    store, client, headers = library
    first = client.post('/api/search/papers', headers=headers, json={'query': '生育支持', 'mode': 'fulltext'}).json()
    assert first['total'] == 24 and len(first['papers']) == 10 and first['has_more']
    second = client.post('/api/search/papers', headers=headers, json={
        'query': '生育支持', 'mode': 'fulltext', 'session': first['session'], 'offset': 10}).json()
    assert len(second['papers']) == 10
    assert not {p['item_id'] for p in first['papers']} & {p['item_id'] for p in second['papers']}
    third = client.post('/api/search/papers', headers=headers, json={
        'query': '生育支持', 'mode': 'fulltext', 'session': first['session'], 'offset': 20}).json()
    assert len(third['papers']) == 4 and not third['has_more']
    assert len(lexical(store, '生育支持')) == 72


def test_abstract_relation_evidence_and_physical_zotero_page(library):
    store, client, headers = library
    paper = client.post('/api/search/papers', headers=headers, json={'query': '生育支持', 'mode': 'fulltext'}).json()['papers'][0]
    assert paper['abstract']['text'] == '研究生育支持与家庭照料。'
    assert '题名' in paper['relation'] and '摘要' in paper['relation'] and '正文' in paper['relation']
    assert len(paper['evidence']) == 1
    evidence = paper['evidence'][0]
    assert evidence['page'] == 2 and evidence['page_label'] == '102'
    assert evidence['zotero_url'].endswith('?page=2')
    assert evidence['zotero_url'].startswith('zotero://open-pdf/library/items/F')
    with store.connect() as db:
        row = dict(db.execute('SELECT * FROM chunks WHERE id=?', (evidence['id'],)).fetchone())
    assert evidence['source_digest'] == fingerprint(row)
    assert '作者单位' not in evidence['text']


def test_pagination_bound_to_filters_generation_and_expiry(library, monkeypatch):
    store, client, headers = library
    query = {'query': '生育支持', 'mode': 'fulltext'}
    first = client.post('/api/search/papers', headers=headers, json=query).json()
    changed = client.post('/api/search/papers', headers=headers, json=query | {'session': first['session'], 'year': '2023'})
    assert changed.status_code == 409
    store.set_state('import_generation', 2)
    assert client.post('/api/search/papers', headers=headers, json=query | {'session': first['session']}).status_code == 409
    first = client.post('/api/search/papers', headers=headers, json=query).json()
    monkeypatch.setattr('sociolit.paper_search.time.monotonic', lambda: float('inf'))
    assert client.post('/api/search/papers', headers=headers, json=query | {'session': first['session']}).status_code == 409


def test_empty_filter_no_model_calls_and_no_unrelated_results(library, monkeypatch):
    _, client, headers = library
    monkeypatch.setattr('sociolit.server.LocalEmbedder', lambda *_: pytest.fail('No model for an empty author filter'))
    result = client.post('/api/search/papers', headers=headers, json={'query': '生育支持', 'author': 'nobody'}).json()
    assert result['total'] == 0
    for payload in ({'query': '生育', 'offset': 10}, {'query': '生育', 'page_size': 100}, {'query': '生育', 'year': 'xx'}):
        assert client.post('/api/search/papers', headers=headers, json=payload).status_code in (400, 422)
    assert client.post('/api/search/papers', json={'query': '生育'}).status_code == 403
    assert client.post('/api/source/location', json={'file_id': 'x', 'page': 1}).status_code == 403


def test_missing_abstract_never_substitutes_arbitrary_page(library):
    store, _, _ = library
    with store.connect() as db:
        assert not abstract_from_pages(db, 'zotero:synthetic:P0000000')['text']
        text = '这是一段明确标识的摘要内容，用于合成测试。' * 5
        store.add_chunk(db, item_id='zotero:synthetic:P0000000', file_id='zotero:synthetic:F0000000', page=1,
                        text='摘要：' + text + '关键词：合成', kind='pdf')
        abstract = abstract_from_pages(db, 'zotero:synthetic:P0000000')
        assert abstract['text'] == text and '第 1 页' in abstract['source']


def test_backmatter_is_a_ranking_signal_not_an_index_deletion():
    assert backmatter('作者单位：合成\n责任编辑：合成')
    assert backmatter('References\nSynthetic (2021)')
    assert not backmatter('研究考察生育支持与家庭照料之间的联系。')


def test_native_opener_uses_only_registered_attachment_not_arbitrary_uri(library, monkeypatch):
    store, _, _ = library
    opened = []
    monkeypatch.setattr('sociolit.desktop.os.startfile', opened.append, raising=False)
    monkeypatch.setattr('sociolit.desktop.os.name', 'nt')
    bridge = DesktopAPI()
    bridge._store = store
    assert bridge.open_source('zotero:synthetic:F0000000', 2)['opened']
    assert opened == ['zotero://open-pdf/library/items/F0000000?page=2']
    for file, page in [('https://example.org', 2), ('zotero:synthetic:F0000000', 999), ('zotero:synthetic:F0000000', True)]:
        with pytest.raises(ValueError):
            bridge.open_source(file, page)
    assert len(opened) == 1


def test_non_zotero_and_malformed_keys_use_local_pdf_fallback(library):
    store, _, _ = library
    with store.connect() as db:
        db.execute("UPDATE items SET source='synthetic-export' WHERE id=?", ('zotero:synthetic:P0000000',))
    assert locate(store, 'zotero:synthetic:F0000000', 2)['zotero_url'] is None


def test_paper_detail_preserves_query_and_selects_exact_item(library):
    _, client, headers = library
    result = client.post('/api/literature/paper', headers=headers,
                         json={'item_id': 'zotero:synthetic:P0000000', 'query': '生育支持'}).json()
    assert result['item_id'] == 'zotero:synthetic:P0000000'
    assert result['evidence'][0]['page'] == 2 and result['relation_excerpt']
    assert client.post('/api/literature/paper', headers=headers, json={'item_id': 'missing'}).status_code == 404
    assert client.post('/api/literature/paper', json={'item_id': 'zotero:synthetic:P0000000'}).status_code == 403


def test_recommendation_reason_does_not_mistake_punctuation_for_a_topic(library):
    store, _, _ = library
    with store.connect() as db:
        db.execute('UPDATE items SET title=? WHERE id=?', ('社区制度——生育决策', 'zotero:synthetic:P0000000'))
        db.execute('UPDATE items SET title=? WHERE id=?', ('劳动变迁——家庭照料', 'zotero:synthetic:P0000001'))
    result = recommend_metadata(store, 'zotero:synthetic:P0000000', limit=100)
    candidate = next(r for r in result['results'] if r['id'] == 'zotero:synthetic:P0000001')
    assert all('——' not in reason for reason in candidate['reasons'])


def test_offline_graph_distribution_has_pinned_digest_and_license():
    static = Path(__file__).parents[1] / 'src/sociolit/static'
    assert sha256((static / 'cytoscape-3.35.0.min.js').read_bytes()).hexdigest() == '71fa9ebec21a7ca2c40cff6aacc30d1f6464e363662ad4b2c197e1adc770cd94'
    assert 'The Cytoscape Consortium' in (static / 'cytoscape-LICENSE.txt').read_text('utf-8')
