import json
import sqlite3
import subprocess
import sys
import tomllib
from hashlib import sha256
from pathlib import Path

import pytest

from sociolit.smoke import seed_upgrade_fixture
from sociolit.status_snapshot import LibraryStatus
from sociolit.store import Store


def test_distribution_and_runtime_versions_match():
    from sociolit import __version__
    project = tomllib.loads((Path(__file__).resolve().parents[1] / 'pyproject.toml').read_text('utf-8'))
    assert project['project']['version'] == __version__


@pytest.fixture
def status_library(tmp_path):
    seed_upgrade_fixture(tmp_path)
    store = Store(tmp_path)
    model = tmp_path / 'models/e5-small'
    (model / 'sociolit-model.json').write_text('{"synthetic":true}', encoding='utf-8')
    key = sha256((model / 'sociolit-model.json').read_bytes()).hexdigest()
    with store.connect() as db:
        db.execute('UPDATE vectors SET model=?', (key,))
    cache = LibraryStatus(store)
    try:
        yield store, cache, model
    finally:
        cache.close()


def test_desktop_import_defers_heavy_runtime_until_after_visible_startup():
    code = "import sys; import sociolit.desktop; assert not set(sys.modules)&{'fastapi','torch','sentence_transformers','pypdf','uvicorn','httpx'}"
    subprocess.run([sys.executable, '-c', code], check=True, timeout=15)


def test_idle_reads_reuse_statistics_but_external_wal_commits_invalidate(status_library, monkeypatch):
    store, cache, model = status_library
    reads, original = [], cache._read

    def counted(*args):
        reads.append(1)
        return original(*args)

    monkeypatch.setattr(cache, '_read', counted)
    first = cache.get('生育演示', model)
    assert first['semantic_progress'] == {'done': 1, 'total': 1}
    first['stats']['items'] = 99
    assert cache.get('生育演示', model)['stats']['items'] == 1 and len(reads) == 1
    # Independent connection/process commits must invalidate, not only API writes.
    with sqlite3.connect(store.path) as writer:
        writer.execute('DELETE FROM vectors')
    assert cache.get('生育演示', model)['semantic_progress']['done'] == 0 and len(reads) == 2
    store.set_state('last_import', {'items_changed': 2, 'warnings': ['private diagnostic']})
    assert cache.get('生育演示', model)['last_import'] == {'items_changed': 2}
    assert len(reads) == 3
    with pytest.raises(sqlite3.OperationalError, match='readonly'):
        cache._observer.execute('CREATE TABLE forbidden(value TEXT)')


def test_scope_model_and_expiry_refresh_without_database_writes(status_library, monkeypatch):
    _store, cache, model = status_library
    clock = [0]
    cache.clock = lambda: clock[0]
    reads, original = [], cache._read

    def counted(*args):
        reads.append(1)
        return original(*args)

    monkeypatch.setattr(cache, '_read', counted)
    cache.get('生育演示', model)
    clock[0] = 29
    cache.get('生育演示', model)
    assert len(reads) == 1
    clock[0] = 30
    cache.get('生育演示', model)
    assert len(reads) == 2
    assert cache.get('其他范围', model)['semantic_progress'] is None
    (model / 'sociolit-model.json').write_text('{"synthetic":2}', encoding='utf-8')
    cache.get('其他范围', model)
    assert len(reads) == 4


def test_concurrent_commit_during_snapshot_is_not_cached(status_library, monkeypatch):
    store, cache, model = status_library
    original, calls = cache._read, []

    def concurrent(*args):
        value = original(*args)
        calls.append(1)
        if len(calls) == 1:
            store.set_state('last_import', {'items_changed': 3})
        return value

    monkeypatch.setattr(cache, '_read', concurrent)
    cache.get('生育演示', model)
    assert cache.get('生育演示', model)['last_import'] == {'items_changed': 3}
    cache.get('生育演示', model)
    assert len(calls) == 2


def test_snapshot_close_releases_database_for_renaming(status_library):
    store, cache, model = status_library
    cache.get('生育演示', model)
    cache.close()
    moved = store.path.with_suffix('.moved')
    store.path.rename(moved)
    moved.rename(store.path)
    assert cache.get('生育演示', model)['stats']['items'] == 1


def test_durable_settings_failure_does_not_replace_previous_file(tmp_path, monkeypatch):
    from sociolit import upgrades
    path = tmp_path / 'settings.json'
    original = b'{"original":true}'
    path.write_bytes(original)

    def failure(_fd):
        raise OSError('Synthetic disk flush failure')

    monkeypatch.setattr(upgrades.os, 'fsync', failure)
    with pytest.raises(OSError, match='flush failure'):
        upgrades._write(path, {'new': True})
    assert path.read_bytes() == original and not list(tmp_path.glob('*.tmp'))
    assert json.loads(path.read_text()) == {'original': True}
