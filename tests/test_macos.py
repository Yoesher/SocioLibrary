import json
from types import SimpleNamespace

import pytest

from sociolit.ai import AIError, MacKeychainProtector
from sociolit.macos import asset_name, open_zotero
from sociolit.software_updates import UpdateError, parse_release


class Vault:
    def __init__(self):
        self.values = {}

    def set_password(self, service, account, value):
        self.values[service, account] = value

    def get_password(self, service, account):
        return self.values.get((service, account))


def test_mac_credentials_are_context_bound_keychain_references():
    vault = Vault()
    protector = MacKeychainProtector(vault)
    reference = protector.protect('synthetic-key', 'connection-one')
    assert 'synthetic-key' not in reference and reference.startswith('keychain:')
    assert protector.unprotect(reference, 'connection-one') == 'synthetic-key'
    with pytest.raises(AIError):
        protector.unprotect(reference, 'different-provider')
    with pytest.raises(AIError):
        protector.unprotect('Windows-ciphertext', 'connection-one')
    assert 'synthetic-key' in json.dumps(vault.values[protector.service, reference[9:]])


def test_mac_source_open_uses_exact_zotero_bundle_and_no_shell():
    calls = []
    def runner(command, **kwargs):
        calls.append(command)
        assert kwargs['timeout'] == 10 and not kwargs.get('shell')
        return SimpleNamespace(returncode=0)
    uri = 'zotero://open-pdf/library/items/AAA11111?page=3'
    open_zotero(uri, runner)
    assert calls == [['/usr/bin/open', '-b', 'org.zotero.zotero', uri]]
    for bad in ('https://example.org', uri+'; command', 'file:///tmp/private'):
        with pytest.raises(ValueError):
            open_zotero(bad, runner)


def test_mac_update_selects_matching_arch_and_refuses_windows_fallback():
    name = asset_name('9.0.0', 'arm64')
    payload = {'draft': False, 'prerelease': False, 'tag_name': 'v9.0.0', 'assets': [
        {'name': name, 'size': 2000000, 'state': 'uploaded', 'digest': 'sha256:'+'a'*64,
         'browser_download_url': 'https://github.com/Yoesher/SocioLibrary/releases/download/v9.0.0/'+name}]}
    assert parse_release(payload, '0.12.0', asset_name=lambda v: asset_name(v, 'arm64')).url.endswith(name)
    with pytest.raises(UpdateError):
        parse_release(payload, '0.12.0', asset_name=lambda v: asset_name(v, 'x86_64'))
    with pytest.raises(UpdateError):
        asset_name('9.0.0', 'unknown')
