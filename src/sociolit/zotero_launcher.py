"""Windows Zotero launch without depending on registered URL associations.

Zotero's official command-line handler accepts -url zotero://open-pdf/...
No registry changes, database access, shell interpolation or file association UI.
"""
import json
import os
import re
import subprocess
from pathlib import Path

_cached = None


def running_paths():
    # Fixed, read-only command. No library text, URI or user input enters PowerShell.
    command = ("[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding; "
               "@(Get-Process -Name zotero -ErrorAction SilentlyContinue | "
               "Select-Object -ExpandProperty Path -Unique) | ConvertTo-Json -Compress")
    try:
        result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', command],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            encoding='utf-8-sig', timeout=5, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), check=False)
        values = json.loads(result.stdout) if result.returncode == 0 and result.stdout.strip() else []
        return [values] if isinstance(values, str) else values if isinstance(values, list) else []
    except (OSError, ValueError, subprocess.SubprocessError):
        return []


def registered_paths():
    import winreg
    paths = []
    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            try:
                with winreg.OpenKey(root, r'Software\Microsoft\Windows\CurrentVersion\App Paths\zotero.exe',
                                    0, winreg.KEY_READ | view) as key:
                    paths.append(winreg.QueryValueEx(key, '')[0])
            except OSError:
                pass
    try:
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r'zotero\shell\open\command') as key:
            command = winreg.QueryValueEx(key, '')[0]
        match = re.match(r'^"([^"\r\n]+\.exe)"(?:\s|$)|^([^"\r\n]+?\.exe)(?:\s|$)', command, re.I)
        if match:
            paths.append(match[1] or match[2])
    except (OSError, TypeError):
        pass
    for name in ('ProgramFiles', 'ProgramFiles(x86)', 'LOCALAPPDATA'):
        if os.environ.get(name):
            base = Path(os.environ[name])
            paths.extend([str(base / 'Zotero/zotero.exe'), str(base / 'Programs/Zotero/zotero.exe')])
    return paths


def valid_path(value):
    if not isinstance(value, str) or not value or value.startswith(('\\\\', '//')) or len(value) > 32767:
        return None
    path = Path(value)
    if not path.is_absolute() or path.name.lower() != 'zotero.exe':
        return None
    try:
        path = path.resolve(strict=True)
        return path if path.is_file() and path.name.lower() == 'zotero.exe' else None
    except (OSError, RuntimeError):
        return None


def find_zotero():
    global _cached
    if _cached and valid_path(str(_cached)):
        return _cached
    for candidate in [*running_paths(), *registered_paths()]:
        path = valid_path(candidate)
        if path:
            _cached = path
            return path
    raise ValueError('未找到 Zotero 程序。请先启动本机 Zotero，再点击原文页；软件不会修改系统默认应用。')


def launch(uri):
    match = re.fullmatch(r'zotero://open-pdf/library/items/[A-Z0-9]{8}\?page=([1-9][0-9]{0,3})', uri)
    if not match or int(match[1]) > 3000:
        raise ValueError('无效的 Zotero 原文链接。')
    executable = find_zotero()
    try:
        subprocess.Popen([str(executable), '-url', uri], stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
    except OSError as exc:
        raise ValueError('Zotero 启动失败，请确认程序位置及本机访问权限。') from exc
