"""Native macOS integration; no shell interpolation or Windows installer fallback."""
import platform
import re
import subprocess

from .software_updates import UpdateError, UpdateManager, fetch_release
from .upgrades import _write


def asset_name(version, machine=None):
    machine = machine or platform.machine()
    if machine not in ('arm64', 'x86_64'):
        raise UpdateError('当前 Mac 架构暂不支持。')
    return f'SocioLibrary-{version}-macOS-{machine}.zip'


def open_zotero(uri, runner=subprocess.run):
    if not re.fullmatch(r'zotero://open-pdf/library/items/[A-Z0-9]{8}\?page=[1-9][0-9]{0,3}', uri):
        raise ValueError('Zotero 页链接无效。')
    try:
        result = runner(['/usr/bin/open', '-b', 'org.zotero.zotero', uri],
                        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10, check=False)
        if result.returncode:
            raise ValueError('请先安装并打开 Zotero，再尝试原文定位。')
    except (OSError, subprocess.SubprocessError):
        raise ValueError('无法启动 Zotero，请检查 Mac 上的客户端安装。') from None


class MacUpdateManager(UpdateManager):
    def _fetch(self, client):
        return fetch_release(client, self._version, asset_name=asset_name)

    def _persist(self):
        # Preview builds check updates but leave application replacement to the user.
        _write(self._path, dict(self._settings, release=None, last_install=None))

    def download(self):
        raise UpdateError('Mac 预览版请从官方发布页下载对应芯片版本，退出后替换应用；资料目录继续沿用。')
