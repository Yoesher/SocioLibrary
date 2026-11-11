import json
import sys
from pathlib import Path

import pytest

from sociolit.upgrades import (
    UpgradeError,
    legacy_location_file,
    location_file,
    physical_directory,
    remember_directory,
    resolve_desktop_directory,
)


def test_database_file_resolves_overlaid_directory_to_physical_library(tmp_path):
    logical, physical = tmp_path / 'logical', tmp_path / 'physical'
    logical.mkdir()
    physical.mkdir()
    database = physical / 'library.sqlite3'
    database.write_bytes(b'Synthetic file-location fixture')
    try:
        (logical / database.name).symlink_to(database)
    except OSError:
        pytest.skip('This account cannot create symbolic links')
    assert physical_directory(logical) == physical
    assert physical_directory(tmp_path / 'new') == tmp_path / 'new'


@pytest.mark.skipif(sys.platform != 'win32', reason='Shared Windows location pointer')
def test_shared_pointer_migrates_legacy_and_survives_a_different_launcher(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, 'home', lambda: tmp_path / 'home')
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / 'launcher-one'))
    monkeypatch.delenv('SOCIOLIT_DATA_DIR', raising=False)
    library = tmp_path / 'research'
    library.mkdir()
    (library / 'library.sqlite3').write_bytes(b'Synthetic library marker')
    legacy = legacy_location_file()
    legacy.parent.mkdir(parents=True)
    legacy.write_text(json.dumps({'data_dir': str(library)}))
    assert resolve_desktop_directory() == library
    remember_directory(library)
    shared = location_file()
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / 'launcher-two'))
    assert location_file() == shared and resolve_desktop_directory() == library
    library.rename(tmp_path / 'disconnected')
    with pytest.raises(UpgradeError, match='原磁盘'):
        resolve_desktop_directory()
    assert not library.exists()
    shared.write_text('invalid pointer')
    with pytest.raises(UpgradeError):
        resolve_desktop_directory()


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows installation context')
def test_inno_installation_is_recognized_even_when_launcher_registry_differs(tmp_path, monkeypatch):
    import winreg

    from sociolit.update_install import native_install_context
    program = tmp_path / 'application'
    program.mkdir()
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, 'executable', str(program / 'SocioLibrary.exe'))
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / 'different-launcher'))
    def absent(*args):
        raise FileNotFoundError('Synthetic registry context')
    monkeypatch.setattr(winreg, 'OpenKey', absent)
    for name in ('unins000.exe', 'unins000.dat'):
        (program / name).write_bytes(b'Synthetic Inno file marker; never executed')
    context = native_install_context()
    assert context['mode'] == 'installed' and context['target'] == str(program)
    (program / 'unins000.dat').unlink()
    assert native_install_context()['mode'] == 'portable'
