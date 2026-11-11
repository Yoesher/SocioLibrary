import io
import json
import zipfile

import pytest
from fastapi.testclient import TestClient

from sociolit import graph, graph_views, journal_inbox
from sociolit.indexing import import_snapshot
from sociolit.server import create_app
from sociolit.store import Store
from sociolit.zotero import Snapshot


@pytest.fixture
def library(tmp_path):
    store = Store(tmp_path)
    import_snapshot(store, Snapshot('zotero:synthetic', [
        {'key': 'ABCDEFGH', 'title': '../Care <script>alert(1)</script>', 'abstract': 'Source abstract', 'tags': ['care']},
        {'key': 'IJKLMNOP', 'title': 'Fertility care evidence', 'tags': ['care']},
    ], [], True))
    create_app(store, {})
    return store


def state():
    ids = ['zotero:synthetic:ABCDEFGH', 'zotero:synthetic:IJKLMNOP']
    return {'ids': ids, 'positions': {key: {'x': i*150, 'y': -30} for i, key in enumerate(ids)},
            'pinned': ids[:1], 'viewport': {'zoom': .8, 'pan': {'x': 120, 'y': -70}},
            'layout': 'network', 'origin': 'all', 'seed': ids[0], 'selected': ids[0],
            'data': {'nodes': [{'id': 'fabricated'}], 'edges': [{'label': 'fake citation'}]}}


def test_saved_map_reopens_preserves_camera_and_distrusts_client_evidence(library):
    saved = graph_views.save(library, 'Core research', state())
    graph_views.initialize(Store(library.directory))
    restored = graph_views.get(Store(library.directory), saved['id'])
    assert restored['state']['positions'] == state()['positions']
    assert restored['state']['viewport'] == state()['viewport']
    assert restored['state']['pinned'] == state()['pinned']
    assert {n['id'] for n in restored['data']['nodes']} == set(state()['ids'])
    assert all(e['origin'] != 'manual' and e['snapshot'] for e in restored['data']['edges'])
    assert 'fake citation' not in json.dumps(restored)
    with library.connect() as db:
        db.execute('DELETE FROM items WHERE id=?', (state()['ids'][0],))
    assert not graph_views.get(library, saved['id'])['data']['nodes'][0]['current']


def test_graph_view_validation_and_archive_conflicts(library):
    for invalid in ({'ids': []}, dict(state(), positions={}), dict(state(), viewport={'zoom': float('nan'), 'pan': {}}),
                    dict(state(), layout='unknown'), dict(state(), pinned=['foreign'])):
        with pytest.raises(ValueError):
            graph_views.save(library, 'bad', invalid)
    saved = graph_views.save(library, 'valid', state())
    graph_views.archive(library, saved['id'], saved['revision'], True)
    assert not graph_views.listing(library) and len(graph_views.listing(library, True)) == 1
    with pytest.raises(ValueError):
        graph_views.archive(library, saved['id'], saved['revision'], False)


def test_portable_export_valid_canvas_safe_paths_and_explicit_annotation_scope(library):
    graph.create_link(library, *state()['ids'], 'cites', 'Synthetic checked reference')
    with library.connect() as db:
        db.execute('INSERT INTO zotero_annotations VALUES(?,?,?,?,?,?,?,?,?)',
                   ('a', 'zotero:synthetic', state()['ids'][0], 'zotero:synthetic:AAA11111',
                    json.dumps({'text': 'Private synthetic highlight', 'comment': 'My interpretation', 'page': 3}), '{}', 'hash', 1, '2026'))
    saved = graph_views.save(library, 'Canvas', state())
    with zipfile.ZipFile(io.BytesIO(graph_views.export(library, saved['id']))) as package:
        assert all(not n.startswith('/') and '..' not in n for n in package.namelist())
        canvas = json.loads(package.read('SocioLibrary.canvas'))
        ids = [n['id'] for n in canvas['nodes']] + [e['id'] for e in canvas['edges']]
        assert len(ids) == len(set(ids))
        assert all(e['fromNode'] in ids and e['toNode'] in ids for e in canvas['edges'])
        assert any(e['toEnd'] == 'arrow' for e in canvas['edges'])
        for node in canvas['nodes']:
            assert node['file'] in package.namelist()
            text = package.read(node['file']).decode()
            assert '<script>' not in text and 'Private synthetic highlight' not in text
            assert str(library.directory) not in text
    with zipfile.ZipFile(io.BytesIO(graph_views.export(library, saved['id'], True))) as package:
        text = '\n'.join(package.read(n).decode() for n in package.namelist())
        assert 'Private synthetic highlight' in text and '个人评论（不是作者原文）' in text
        assert 'zotero://open-pdf/library/items/AAA11111?page=3' in text


def ingest(store, count=25, title='Journal paper'):
    import_snapshot(store, Snapshot(journal_inbox.SOURCE, [
        {'key': str(i), 'title': title+' '+str(i), 'authors': ['Synthetic'], 'year': '1995',
         'raw': {'journal': 'Synthetic Journal', 'published_date': '1995-01-01', 'url': 'https://example.org/article'}}
        for i in range(count)], [], True))
    journal_inbox.sync(store)


def test_inbox_pagination_literal_search_and_durable_triage(library):
    ingest(library)
    first = journal_inbox.listing(library)
    second = journal_inbox.listing(library, offset=20)
    assert first['total'] == 25 and len(first['records']) == 20 and len(second['records']) == 5
    assert not {r['item_id'] for r in first['records']} & {r['item_id'] for r in second['records']}
    key = first['records'][0]['item_id']
    journal_inbox.mark(library, key, True, True)
    journal_inbox.sync(Store(library.directory))
    assert journal_inbox.listing(library)['total'] == 24
    assert journal_inbox.listing(library, state='favorites')['records'][0]['read']
    assert not journal_inbox.listing(library, query='%')['records']
    ingest(library, title='Corrected journal title')
    row = journal_inbox.listing(library, state='favorites')['records'][0]
    assert row['favorite'] and not row['read'] and row['updated_record']
    assert row['published_date'][:4] == '1995' and row['first_seen'][:4] != '1995'


def test_new_workspace_routes_require_session_origin_and_preserve_busy_work(library):
    app = create_app(library, {})
    with TestClient(app, base_url='http://127.0.0.1') as client:
        h = {'X-Sociolit-Token': client.get('/api/status').json()['token']}
        payload = {'name': 'Route map', 'state': state()}
        assert client.get('/api/graph/views').status_code == 403
        assert client.post('/api/graph/views', json=payload, headers=dict(h, Origin='https://foreign.example')).status_code == 403
        app.state.operation_lock.acquire()
        try:
            assert client.post('/api/graph/views', json=payload, headers=h).status_code == 409
        finally:
            app.state.operation_lock.release()
        saved = client.post('/api/graph/views', json=payload, headers=h).json()
        assert client.get('/api/graph/views/'+saved['id'], headers=h).status_code == 200
        response = client.post('/api/graph/views/'+saved['id']+'/export', json={}, headers=h)
        assert response.status_code == 200 and zipfile.is_zipfile(io.BytesIO(response.content))
        assert client.get('/api/journals/inbox?state=invalid', headers=h).status_code == 400
