import json
import os
import sqlite3
import threading
from hashlib import sha256

import pytest

from sociolit import __version__, startup
from sociolit.desktop import initialize_desktop_library
from sociolit.smoke import seed_upgrade_fixture
from sociolit.upgrades import UpgradeCancelled, UpgradeError, prepare_upgrade


@pytest.mark.parametrize('stage', ['备份原资料', '校验备份', '保存升级备份'])
def test_cancelled_upgrade_preserves_source_version_and_removes_partial_snapshot(tmp_path, stage):
    seed_upgrade_fixture(tmp_path)
    original = sha256((tmp_path / 'library.sqlite3').read_bytes()).digest()
    marker = (tmp_path / 'desktop-version.json').read_bytes()

    def cancel_at(label, percent):
        if label.startswith(stage):
            raise UpgradeCancelled('Synthetic cancellation')

    with pytest.raises(UpgradeCancelled):
        initialize_desktop_library(tmp_path, progress=cancel_at)
    assert sha256((tmp_path / 'library.sqlite3').read_bytes()).digest() == original
    assert (tmp_path / 'desktop-version.json').read_bytes() == marker
    assert not list((tmp_path / 'backups').iterdir())
    initialize_desktop_library(tmp_path)
    assert json.loads((tmp_path / 'desktop-version.json').read_text('utf-8'))['version'] == __version__


def test_validation_cancellation_interrupts_sqlite_and_preserves_original(tmp_path):
    seed_upgrade_fixture(tmp_path)
    with sqlite3.connect(tmp_path / 'library.sqlite3') as db:
        db.execute('CREATE TABLE synthetic_validation(value TEXT)')
        db.executemany('INSERT INTO synthetic_validation VALUES (?)', [('synthetic',)] * 5000)
    original = sha256((tmp_path / 'library.sqlite3').read_bytes()).digest()
    calls = []

    def cancel_during_validation(stage, _percent):
        if stage.startswith('校验备份'):
            calls.append(stage)
            if len(calls) > 1:
                raise UpgradeCancelled('Synthetic validation cancellation')

    with pytest.raises(UpgradeCancelled):
        prepare_upgrade(tmp_path, __version__, progress=cancel_during_validation)
    assert len(calls) == 2
    assert sha256((tmp_path / 'library.sqlite3').read_bytes()).digest() == original
    assert not list((tmp_path / 'backups').iterdir())


def test_validation_timeout_is_bounded_as_well_as_copying(tmp_path, monkeypatch):
    from sociolit import upgrades
    seed_upgrade_fixture(tmp_path)
    with sqlite3.connect(tmp_path / 'library.sqlite3') as db:
        db.execute('CREATE TABLE synthetic_validation(value TEXT)')
        db.executemany('INSERT INTO synthetic_validation VALUES (?)', [('synthetic',)] * 5000)
    clock = [0]
    monkeypatch.setattr(upgrades.time, 'monotonic', lambda: clock[0])

    def jump_clock(stage, _percent):
        if stage.startswith('校验备份'):
            clock[0] = 601

    with pytest.raises(UpgradeError, match='校验超时'):
        prepare_upgrade(tmp_path, __version__, progress=jump_clock)
    assert not list((tmp_path / 'backups').iterdir())


@pytest.mark.skipif(os.name != 'nt', reason='Windows instance identity')
def test_stale_pid_record_does_not_activate_another_process(tmp_path, monkeypatch):
    record = tmp_path / 'desktop-instance.json'
    record.write_text(json.dumps({'pid': 42, 'created': 100}), encoding='utf-8')
    monkeypatch.setattr(startup, '_creation_time', lambda _: 101)
    monkeypatch.setattr(startup, '_activate', lambda _: pytest.fail('Must not activate a reused PID'))
    assert not startup.activate_existing(tmp_path, wait=0)
    record.write_text('corrupt synthetic record', encoding='utf-8')
    assert not startup.activate_existing(tmp_path, wait=0)


@pytest.mark.skipif(os.name != 'nt', reason='Native Windows initialization window')
def test_native_progress_window_activates_and_cancel_stops_backup_safely(tmp_path):
    seed_upgrade_fixture(tmp_path)
    original = sha256((tmp_path / 'library.sqlite3').read_bytes()).digest()
    instance = startup.DesktopInstance(tmp_path)
    window = startup.StartupWindow()
    try:
        window.start()
        assert window._hwnd and window._thread.is_alive()
        # Test only our own synthetic window, never the user's desktop windows.
        assert startup.activate_existing(tmp_path, wait=0)
        window.update('备份原资料', 37)
        window._post(0x10)
        assert window.cancelled.wait(5)
        with pytest.raises(UpgradeCancelled):
            initialize_desktop_library(tmp_path, progress=window.update)
        assert sha256((tmp_path / 'library.sqlite3').read_bytes()).digest() == original
    finally:
        window.close()
        instance.close()
    assert not window._thread.is_alive()
    assert not (tmp_path / 'desktop-instance.json').exists()


def test_cancel_during_copy_is_cooperative_and_holds_caller_until_cleanup(tmp_path):
    seed_upgrade_fixture(tmp_path)
    with sqlite3.connect(tmp_path / 'library.sqlite3') as db:
        db.execute('CREATE TABLE synthetic_large(value BLOB)')
        db.executemany('INSERT INTO synthetic_large VALUES (?)', [(b'x' * 8192,)] * 200)
    window = startup.StartupWindow()
    observed = threading.Event()
    completed = threading.Event()
    failures = []

    def progress(stage, percent):
        if stage == '备份原资料' and percent and percent < 100:
            observed.set()
            assert window.cancelled.wait(5)
        window.update(stage, percent)

    def run():
        try:
            initialize_desktop_library(tmp_path, progress=progress)
        except UpgradeCancelled:
            pass
        except Exception as exc:
            failures.append(exc)
        finally:
            completed.set()

    worker = threading.Thread(target=run)
    worker.start()
    try:
        assert observed.wait(5)
        assert not completed.is_set()
        window.cancelled.set()
        assert completed.wait(5)
        assert not failures and not list((tmp_path / 'backups').iterdir())
    finally:
        window.cancelled.set()
        worker.join(5)


@pytest.mark.skipif(os.name != 'nt', reason='Windows instance record cleanup')
def test_instance_cleanup_does_not_delete_a_replaced_record(tmp_path):
    instance = startup.DesktopInstance(tmp_path)
    replacement = {'pid': 42, 'created': 100}
    instance.path.write_text(json.dumps(replacement), encoding='utf-8')
    instance.close()
    assert json.loads(instance.path.read_text('utf-8')) == replacement
