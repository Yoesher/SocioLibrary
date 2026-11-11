import json
import sqlite3
from hashlib import sha256
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from filelock import FileLock

from sociolit import __version__
from sociolit.desktop import initialize_desktop_library
from sociolit.smoke import check_upgrade_fixture, seed_upgrade_fixture
from sociolit.upgrades import (
    UpgradeError,
    complete_upgrade,
    location_file,
    prepare_upgrade,
    remember_directory,
    resolve_desktop_directory,
)


def test_settings_write_retries_brief_windows_file_contention(tmp_path, monkeypatch):
    from sociolit import upgrades
    path = tmp_path / 'settings.json'
    path.write_text('{"old":true}', encoding='utf-8')
    replace, attempts = upgrades.os.replace, []

    def blocked_once(source, destination):
        attempts.append(1)
        assert path.read_text('utf-8') == '{"old":true}'
        if len(attempts) == 1:
            raise PermissionError('Synthetic sharing contention')
        replace(source, destination)

    monkeypatch.setattr(upgrades.os, 'replace', blocked_once)
    monkeypatch.setattr(upgrades.time, 'sleep', lambda _: None)
    upgrades._write(path, {'new': True})
    assert len(attempts) == 2 and json.loads(path.read_text('utf-8')) == {'new': True}


def test_settings_write_keeps_original_on_persistent_access_failure(tmp_path, monkeypatch):
    from sociolit import upgrades
    path = tmp_path / 'settings.json'
    path.write_text('{"old":true}', encoding='utf-8')

    def blocked(*_):
        raise PermissionError('Synthetic permanent access failure')

    monkeypatch.setattr(upgrades.os, 'replace', blocked)
    monkeypatch.setattr(upgrades.time, 'sleep', lambda _: None)
    with pytest.raises(PermissionError):
        upgrades._write(path, {'new': True})
    assert json.loads(path.read_text('utf-8')) == {'old': True} and not list(tmp_path.glob('*.tmp'))


def test_upgrade_inherits_every_research_table_preferences_model_and_does_not_repeat_backup(tmp_path):
    seed_upgrade_fixture(tmp_path)
    with sqlite3.connect(tmp_path / "library.sqlite3") as before:
        original = list(before.iterdump())
    preferences = (tmp_path / "preferences.json").read_bytes()
    store, config, app = initialize_desktop_library(tmp_path)
    assert check_upgrade_fixture(tmp_path, store)["snapshot_verified"]
    assert config["semantic"]["collection_keywords"] == ["生育演示"]
    assert (tmp_path / "preferences.json").read_bytes() == preferences
    backup = next((tmp_path / "backups").iterdir())
    with sqlite3.connect(backup / "library.sqlite3") as snapshot:
        assert list(snapshot.iterdump()) == original
    with TestClient(app, base_url="http://localhost") as client:
        status = client.get("/api/status").json()
        assert status["upgrade"]["backup_ready"]
        expanded = client.post('/api/graph/expand', headers={'X-Sociolit-Token': status['token']},
                               json={'seed': 'synthetic:item', 'known_ids': ['synthetic:item'],
                                     'include_auto': False})
        assert expanded.status_code == 200 and expanded.json()['added_ids'] == ['synthetic:gone']
        assert any(n['id'] == 'synthetic:gone' and not n['current'] for n in expanded.json()['nodes'])
    initialize_desktop_library(tmp_path)
    assert list((tmp_path / "backups").iterdir()) == [backup]


def test_backup_contains_committed_wal_data_and_does_not_change_source_bytes(tmp_path):
    seed_upgrade_fixture(tmp_path)
    with sqlite3.connect(tmp_path / "library.sqlite3") as writer:
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("UPDATE reading_notes SET body='Committed WAL evidence'")
        writer.commit()
        before = sha256((tmp_path / "library.sqlite3").read_bytes()).digest()
        report = prepare_upgrade(tmp_path, __version__)
        assert sha256((tmp_path / "library.sqlite3").read_bytes()).digest() == before
        with sqlite3.connect(tmp_path / report["backup"] / "library.sqlite3") as snapshot:
            assert snapshot.execute("SELECT body FROM reading_notes").fetchone()[0] == "Committed WAL evidence"


def test_insufficient_space_stops_before_schema_or_version_changes(tmp_path, monkeypatch):
    seed_upgrade_fixture(tmp_path)
    original = (tmp_path / "library.sqlite3").read_bytes()
    marker = (tmp_path / "desktop-version.json").read_bytes()
    monkeypatch.setattr("sociolit.upgrades.shutil.disk_usage", lambda _: SimpleNamespace(free=0))
    with pytest.raises(UpgradeError, match="空间不足"):
        initialize_desktop_library(tmp_path)
    assert (tmp_path / "library.sqlite3").read_bytes() == original
    assert (tmp_path / "desktop-version.json").read_bytes() == marker
    assert not (tmp_path / "backups").exists()


def test_failed_preferences_load_keeps_old_version_and_valid_recovery_snapshot(tmp_path):
    seed_upgrade_fixture(tmp_path)
    (tmp_path / "preferences.json").write_text("invalid synthetic settings", encoding="utf-8")
    with pytest.raises(ValueError):
        initialize_desktop_library(tmp_path)
    assert json.loads((tmp_path / "desktop-version.json").read_text())["version"] == "0.3.0"
    backup = next((tmp_path / "backups").iterdir())
    with sqlite3.connect(backup / "library.sqlite3") as db:
        assert db.execute("SELECT count(*) FROM reading_notes").fetchone()[0] == 1


def test_downgrade_and_busy_library_are_blocked_before_modifying_data(tmp_path):
    seed_upgrade_fixture(tmp_path)
    marker = tmp_path / "desktop-version.json"
    marker.write_text(json.dumps({"version": "99.0.0"}), encoding="utf-8")
    before = (tmp_path / "library.sqlite3").read_bytes()
    with pytest.raises(UpgradeError, match="更新版本"):
        initialize_desktop_library(tmp_path)
    marker.write_text(json.dumps({"version": "0.3.0"}), encoding="utf-8")
    with FileLock(str(tmp_path / "library.lock")):
        with pytest.raises(UpgradeError, match="其他任务"):
            initialize_desktop_library(tmp_path)
    assert (tmp_path / "library.sqlite3").read_bytes() == before


def test_remembers_custom_folder_respects_overrides_and_never_silently_replaces_missing_library(tmp_path, monkeypatch):
    profile = tmp_path / "profile"
    profile.mkdir()
    monkeypatch.setenv("LOCALAPPDATA", str(profile))
    monkeypatch.delenv("SOCIOLIT_DATA_DIR", raising=False)
    assert resolve_desktop_directory() == profile / "SocioLit"
    custom = tmp_path / "custom"
    custom.mkdir()
    (custom / "library.sqlite3").write_bytes(b"Synthetic path-resolution placeholder")
    remember_directory(custom)
    assert resolve_desktop_directory() == custom
    override = tmp_path / "override"
    monkeypatch.setenv("SOCIOLIT_DATA_DIR", str(override))
    assert resolve_desktop_directory() == override
    assert resolve_desktop_directory(custom) == custom
    monkeypatch.delenv("SOCIOLIT_DATA_DIR")
    custom.rename(tmp_path / "disconnected")
    with pytest.raises(UpgradeError, match="原磁盘"):
        resolve_desktop_directory()
    assert not custom.exists()
    location_file().write_text("corrupt synthetic pointer", encoding="utf-8")
    with pytest.raises(UpgradeError, match="无法读取"):
        resolve_desktop_directory()


def test_legacy_library_without_marker_and_fresh_install(tmp_path):
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    report = prepare_upgrade(fresh, __version__)
    assert not report["inherited"] and not report["backup"]
    complete_upgrade(fresh, report)
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    seed_upgrade_fixture(legacy)
    (legacy / "desktop-version.json").unlink()
    store, _, _ = initialize_desktop_library(legacy)
    assert store.stats()["vectors"] == 1
    assert json.loads((legacy / "desktop-version.json").read_text())["previous_version"] == "legacy"


@pytest.mark.parametrize("failure", ["corrupt_database", "settings_copy_failure"])
def test_failed_backup_keeps_original_and_never_publishes_partial_snapshot(tmp_path, monkeypatch, failure):
    seed_upgrade_fixture(tmp_path)
    if failure == "corrupt_database":
        (tmp_path / "library.sqlite3").write_bytes(b"corrupt synthetic SQLite input")
    else:
        def fail_copy(*_):
            raise OSError("Synthetic copy failure")
        monkeypatch.setattr("sociolit.upgrades.shutil.copy2", fail_copy)
    original = (tmp_path / "library.sqlite3").read_bytes()
    marker = (tmp_path / "desktop-version.json").read_bytes()
    with pytest.raises(UpgradeError, match="无法完成"):
        initialize_desktop_library(tmp_path)
    assert (tmp_path / "library.sqlite3").read_bytes() == original
    assert (tmp_path / "desktop-version.json").read_bytes() == marker
    assert not list((tmp_path / "backups").iterdir())


@pytest.mark.parametrize("version", ["0.3.0", __version__])
def test_missing_database_is_never_silently_recreated_for_an_existing_profile(tmp_path, version):
    seed_upgrade_fixture(tmp_path)
    (tmp_path / "desktop-version.json").write_text(json.dumps({"version": version}), encoding="utf-8")
    (tmp_path / "library.sqlite3").unlink()
    with pytest.raises(UpgradeError, match="数据库文件缺失"):
        initialize_desktop_library(tmp_path)
    assert not (tmp_path / "library.sqlite3").exists()


def test_an_unrecognized_database_is_not_given_soc_library_tables(tmp_path):
    with sqlite3.connect(tmp_path / "library.sqlite3") as db:
        db.execute("CREATE TABLE unrelated (value TEXT)")
        db.execute("INSERT INTO unrelated VALUES('synthetic unrelated database')")
    original = (tmp_path / "library.sqlite3").read_bytes()
    with pytest.raises(UpgradeError, match="未被识别"):
        initialize_desktop_library(tmp_path)
    assert (tmp_path / "library.sqlite3").read_bytes() == original
    assert not list((tmp_path / "backups").iterdir())


def test_auto_update_choice_is_inherited_and_included_in_pre_upgrade_snapshot(tmp_path):
    from sociolit.software_updates import UpdateManager
    seed_upgrade_fixture(tmp_path)
    UpdateManager(tmp_path, "0.3.1").set_automatic(False)
    _, _, app = initialize_desktop_library(tmp_path)
    assert not app.state.updater.snapshot()["auto_check"]
    backup = next((tmp_path / "backups").iterdir())
    assert not json.loads((backup / "software-update.json").read_text(encoding="utf-8"))["auto_check"]
