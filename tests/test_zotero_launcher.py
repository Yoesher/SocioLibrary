from types import SimpleNamespace

import pytest

from sociolit import zotero_launcher as launcher


def test_portable_running_zotero_opens_page_without_system_url_association(tmp_path, monkeypatch):
    executable = tmp_path / 'zotero.exe'
    executable.write_bytes(b'Synthetic executable placeholder; never run')
    monkeypatch.setattr(launcher, '_cached', None)
    monkeypatch.setattr(launcher, 'running_paths', lambda: [str(executable)])
    monkeypatch.setattr(launcher, 'registered_paths', lambda: [])
    calls = []
    monkeypatch.setattr(launcher.subprocess, 'Popen', lambda args, **kwargs: calls.append((args, kwargs)))
    uri = 'zotero://open-pdf/library/items/ABCD1234?page=23'
    launcher.launch(uri)
    assert calls[0][0] == [str(executable), '-url', uri]
    assert 'shell' not in calls[0][1]
    assert launcher.find_zotero() == executable


def test_no_zotero_is_an_error_instead_of_openwith_dialog(monkeypatch):
    monkeypatch.setattr(launcher, '_cached', None)
    monkeypatch.setattr(launcher, 'running_paths', lambda: [])
    monkeypatch.setattr(launcher, 'registered_paths', lambda: [])
    with pytest.raises(ValueError, match='先启动'):
        launcher.launch('zotero://open-pdf/library/items/ABCD1234?page=1')


@pytest.mark.parametrize('uri', ['https://example.org', 'zotero://debugger',
                                'zotero://open-pdf/library/items/ABCD1234?page=3001',
                                'zotero://open-pdf/library/items/ABCD1234?page=1&command=evil'])
def test_launcher_cannot_accept_arbitrary_commands(uri, monkeypatch):
    monkeypatch.setattr(launcher, 'find_zotero', lambda: pytest.fail('Must validate before discovering an executable'))
    with pytest.raises(ValueError):
        launcher.launch(uri)


def test_fixed_process_lookup_handles_unicode_json_and_failure(monkeypatch):
    calls = []

    def run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=0, stdout='["C:/Synthetic/Zotero/zotero.exe"]')

    monkeypatch.setattr(launcher.subprocess, 'run', run)
    assert launcher.running_paths() == ['C:/Synthetic/Zotero/zotero.exe']
    assert calls[0][0][:3] == ['powershell.exe', '-NoProfile', '-NonInteractive']
    assert 'Get-Process -Name zotero' in calls[0][0][-1]
    assert not launcher.valid_path('\\\\server\\share\\zotero.exe')
    assert not launcher.valid_path('zotero.exe')
    assert not launcher.valid_path('C:/Synthetic/not-zotero.exe')
