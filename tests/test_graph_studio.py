import json
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sociolit import graph
from sociolit.indexing import import_snapshot
from sociolit.server import create_app
from sociolit.store import Store
from sociolit.zotero import Snapshot


@pytest.fixture
def network(tmp_path):
    store = Store(tmp_path)
    items = [{'key': str(i), 'title': f'Care fertility policy evidence {i}',
              'tags': ['shared care'], 'authors': ['Synthetic'], 'year': 2020 + i % 5}
             for i in range(100)]
    items += [{'key': 'orphan' + str(i), 'title': '000 unrelated isolate ' + str(i), 'tags': []}
              for i in range(20)]
    import_snapshot(store, Snapshot('synthetic', items, [], True))
    create_app(store, {})
    return store


def test_overview_prioritizes_connected_material_without_inventing_relations(network):
    result = graph.build(network, limit=15)
    assert result['edges']
    assert not any(n['id'].startswith('synthetic:orphan') for n in result['nodes'])
    assert all(e['origin'] != 'manual' for e in result['edges'])
    assert result['limited']


def test_expansion_is_bounded_incremental_and_read_only(network):
    first = graph.build(network, seed='synthetic:0', limit=10)
    known = [n['id'] for n in first['nodes']]
    stats = network.stats()
    result = graph.expand_neighbors(network, 'synthetic:0', known, limit=8)
    assert len(result['added_ids']) == 8
    assert not set(result['added_ids']) & set(known)
    allowed = set(known + result['added_ids'])
    assert all(e['source'] in allowed and e['target'] in allowed for e in result['edges'])
    assert network.stats() == stats
    full = [n['id'] for n in graph.build(network, seed='synthetic:0', limit=80)['nodes']]
    capped = graph.expand_neighbors(network, 'synthetic:0', full)
    assert capped['added_ids'] == [] and capped['capacity_reached']


def test_automatic_ids_are_stable_across_different_views(network):
    a = graph.build(network, seed='synthetic:0', limit=10)
    b = graph.build(network, seed='synthetic:0', limit=30)
    mapping = {(e['origin'], frozenset([e['source'], e['target']]), e['label']): e['id'] for e in b['edges']}
    for e in a['edges']:
        key = (e['origin'], frozenset([e['source'], e['target']]), e['label'])
        if key in mapping:
            assert e['id'] == mapping[key]


def test_expand_api_authorization_bounds_and_manual_only(network):
    with TestClient(create_app(network, {}), base_url='http://localhost') as client:
        value = {'seed': 'synthetic:0', 'known_ids': ['synthetic:0'], 'include_auto': False}
        assert client.post('/api/graph/expand', json=value).status_code == 403
        headers = {'X-Sociolit-Token': client.get('/api/status').json()['token']}
        result = client.post('/api/graph/expand', headers=headers, json=value)
        assert result.status_code == 200 and not result.json()['added_ids']
        assert client.post('/api/graph/expand', headers=headers, json={**value, 'known_ids': []}).status_code == 400
        assert client.post('/api/graph/expand', headers=headers, json={**value, 'limit': 13}).status_code == 422
        assert client.post('/api/graph/expand', headers=headers, json={**value, 'known_ids': ['x'] * 81}).status_code == 422
        assert client.post('/api/graph/expand', headers={**headers, 'Origin': 'https://evil.example'}, json=value).status_code == 403
        with network.connect() as db:
            assert db.execute('SELECT count(*) FROM literature_links').fetchone()[0] == 0


def test_graph_core_offline_node_checks():
    node = shutil.which('node')
    if not node:
        pytest.skip('Node is only needed for contributor JavaScript tests')
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run([node, '--test', 'tests/js/graph-core.test.cjs'], cwd=root,
                            text=True, encoding='utf-8', capture_output=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr


def test_overview_keeps_manual_connections_when_automatic_clues_are_disabled(network):
    graph.create_link(network, 'synthetic:orphan1', 'synthetic:orphan2', 'theory', 'Synthetic evidence')
    result = graph.build(network, limit=10, include_auto=False)
    assert {n['id'] for n in result['nodes']} >= {'synthetic:orphan1', 'synthetic:orphan2'}
    assert len(result['edges']) == 1 and result['edges'][0]['origin'] == 'manual'
    assert json.loads(json.dumps(result))['edges'][0]['note'] == 'Synthetic evidence'
