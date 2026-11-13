import importlib.util
import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from sociolit import appearance, comparisons, research_profiles
from sociolit.ai import AIError, Profiles
from sociolit.ai_context import TASKS, AIWorkspace, fingerprint
from sociolit.comparison_ai import ComparisonAI
from sociolit.crosslanguage import expand, search
from sociolit.indexing import import_snapshot
from sociolit.preferences import save_preferences
from sociolit.server import create_app
from sociolit.store import Store
from sociolit.zotero import Snapshot

CASES = [
    ('教育公平', 'Educational equity', 'education'),
    ('收入不平等', 'Income inequality', 'economics'),
    ('政策执行', 'Policy implementation', 'policy'),
    ('自我效能', 'Self-efficacy', 'psychology'),
    ('生育意愿', 'Fertility intentions', 'sociology'),
    ('媒介素养', 'Media literacy', 'communication'),
    ('空间正义', 'Spatial justice', 'geography'),
    ('档案研究', 'Archival research', 'history'),
    ('参与观察', 'Participant observation', 'anthropology'),
    ('法律意识', 'Legal consciousness', 'law'),
]


@pytest.fixture
def library(tmp_path):
    store = Store(tmp_path)
    items = [dict(key=identity, title=english + ' — synthetic example',
                  abstract='Original demonstration text, not a real publication.', year=2026)
             for _, english, identity in CASES]
    import_snapshot(store, Snapshot('synthetic', items, [], True))
    return store


@pytest.mark.parametrize('query,title,identity', CASES)
def test_cross_disciplinary_chinese_queries_find_english_without_a_model(library, query, title, identity):
    def missing():
        raise RuntimeError('Model not configured')
    # Unrelated selected lenses must never exclude other disciplines.
    research_profiles.save(library.directory, 'sociology')
    rows, info = search(library, query, None, missing)
    assert any(row['item_id'] == 'synthetic:' + identity for row in rows)
    assert not info['semantic'] and info['expanded_queries']
    assert query in expand(title)


def test_term_boundaries_longest_match_and_query_budget():
    assert expand('教育公平') == ['educational equity', 'educational equality']
    assert not expand('ethnographyx')
    assert len(expand('教育公平 人力资本 政策执行 自我效能 空间正义')) <= 8
    assert all(len(query) <= 200 for query in expand('教育公平 人力资本 政策执行 自我效能'))


def test_profile_changes_preserve_settings_and_do_not_reindex(library):
    save_preferences({}, library.directory, [str(library.directory)], ['生育', '婚育'])
    appearance.save(library.directory, appearance.DEFAULTS)
    path = library.directory / 'preferences.json'
    previous = json.loads(path.read_text('utf-8'))
    stats = library.stats()
    research_profiles.save(library.directory, 'history')
    after = json.loads(path.read_text('utf-8'))
    assert after == {**previous, 'research_profile': 'history'}
    assert library.stats() == stats
    save_preferences({}, library.directory, [str(library.directory)], ['生育'])
    appearance.save(library.directory, {**appearance.DEFAULTS, 'theme': 'ink'})
    assert research_profiles.current(library.directory)['id'] == 'history'
    assert json.loads(path.read_text('utf-8'))['collection_keywords'] == ['生育']
    before = path.read_bytes()
    with pytest.raises(ValueError):
        research_profiles.save(library.directory, 'invented')
    assert path.read_bytes() == before


def test_legacy_defaults_and_corrupt_file_are_not_rewritten(tmp_path):
    assert research_profiles.current(tmp_path)['id'] == 'general'
    assert not (tmp_path / 'preferences.json').exists()
    path = tmp_path / 'preferences.json'
    path.write_text(json.dumps({'research_profile': ['unknown'], 'other': 9}))
    before = path.read_bytes()
    assert research_profiles.current(tmp_path)['id'] == 'general'
    assert path.read_bytes() == before
    path.write_text('broken')
    with pytest.raises(ValueError):
        research_profiles.save(tmp_path, 'education')
    assert path.read_text() == 'broken'


def test_profile_routes_are_authenticated_and_do_not_enable_subscriptions(library):
    config = {'journals': [{'name': 'Synthetic original', 'enabled': False, 'sources': []}]}
    with TestClient(create_app(library, config), base_url='http://localhost') as client:
        assert client.get('/api/research/profile').status_code == 403
        headers = {'X-Sociolit-Token': client.get('/api/status').json()['token']}
        catalog = client.get('/api/research/profile', headers=headers).json()
        assert len(catalog['profiles']) == 11 and catalog['current'] == 'general'
        for profile in catalog['profiles']:
            assert len(profile['examples']) == 3
        body = {'identity': 'education'}
        assert client.post('/api/research/profile', json=body, headers={**headers, 'Origin': 'https://evil.example'}).status_code == 403
        assert client.post('/api/research/profile', json=body, headers=headers).json()['current'] == 'education'
        assert client.post('/api/research/profile', json={'identity': 'unknown'}, headers=headers).status_code == 400
        assert not client.get('/api/status').json()['journals'][0]['enabled']


@pytest.fixture
def workspace(library):
    profiles = Profiles(library.directory)
    identity = profiles.save(identity=None, name='Synthetic local', protocol='responses',
                             base_url='http://127.0.0.1:1234/v1', model='synthetic', max_output_tokens=1024)['id']
    seen = []

    def handle(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={'status': 'completed', 'output': [
            {'type': 'message', 'content': [{'type': 'output_text', 'text': '演示草稿 [S1]'}]}]})
    space = AIWorkspace(library, profiles, factory=lambda: httpx.Client(transport=httpx.MockTransport(handle)))
    with library.connect() as db:
        rows = db.execute('SELECT * FROM chunks ORDER BY item_id LIMIT 2').fetchall()
        selections = [dict(chunk_id=row['id'], digest=fingerprint(row)) for row in rows]
    return space, identity, selections, seen


@pytest.mark.parametrize('task', ['methods', 'evidence_map', 'review_outline'])
def test_new_tasks_preview_locally_then_send_exact_reviewed_prompt_once(workspace, task):
    space, identity, selections, seen = workspace
    research_profiles.save(space.store.directory, 'history')
    preview = space.prepare(identity, '如何组织证据？', task, selections)
    assert not seen and preview['research_profile'] == '历史与历史社会科学'
    assert TASKS[task] in preview['prompt']
    assert '不强行要求样本' in preview['system'] and '史料' in preview['system']
    answer = space.ask(preview['confirmation'])
    assert seen[0]['instructions'] == preview['system'] and seen[0]['input'] == preview['prompt']
    assert '历史与历史社会科学' in space.draft(answer['id'])[1]
    with pytest.raises(AIError):
        space.ask(preview['confirmation'])
    assert len(seen) == 1


def test_reading_and_comparison_stop_before_sending_after_lens_change(workspace):
    space, identity, selections, seen = workspace
    reading = space.prepare(identity, '证据', 'ask', selections)
    comparisons.initialize(space.store)
    board = comparisons.create(space.store, '跨学科演示比较', selections)
    matrix = ComparisonAI(space.store, space)
    preview = matrix.prepare(board['id'], identity)
    assert '社会科学文献对照助手' in preview['system']
    research_profiles.save(space.store.directory, 'education')
    with pytest.raises(AIError, match='研究领域已变化'):
        space.ask(reading['confirmation'])
    with pytest.raises(AIError, match='研究领域已变化'):
        matrix.ask(preview['confirmation'])
    assert not seen
    assert comparisons.get(space.store, board['id'])['revision'] == board['revision']


def test_demo_generator_uses_original_pdf_pages_and_refuses_existing_library(tmp_path):
    script = Path(__file__).parents[1] / 'scripts/create_social_science_demo.py'
    spec = importlib.util.spec_from_file_location('social_demo', script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    directory = tmp_path / 'isolated-demo'
    module.create(directory)
    store = Store(directory)
    assert store.stats()['items'] == 10 and store.stats()['files'] == 10
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM chunks WHERE kind='pdf'").fetchone()[0] == 20
        assert all('NOT a real publication' in row['text'] for row in db.execute("SELECT text FROM chunks WHERE kind='pdf' AND page=1"))
    assert '非真实论文' in (directory / 'DEMO-ONLY.txt').read_text('utf-8')
    before = store.stats()
    with pytest.raises(ValueError, match='新的空文件夹'):
        module.create(directory)
    assert store.stats() == before
