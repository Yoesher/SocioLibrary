"""Remove only verified obsolete program files; never visit research directories."""
import base64
import csv
import hashlib
import json
import re
import stat
from email.parser import Parser
from pathlib import Path


def _project(name):
    return re.sub(r'[-_.]+', '-', name).lower()


def _safe(path, root):
    """Reject symlinks/junctions at every level below the installation root."""
    try:
        relative = path.relative_to(root)
        if not relative.parts or not path.resolve().is_relative_to(root.resolve()):
            return False
        current = root
        for part in relative.parts:
            current /= part
            info = current.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                return False
        return True
    except (OSError, ValueError):
        return False


def _digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _remove_empty_parents(path, boundary):
    while path != boundary and path.is_relative_to(boundary):
        try:
            path.rmdir()
        except OSError:
            break
        path = path.parent


def _metadata_files(folder, root, projects):
    """A wheel RECORD must account for and authenticate every existing file."""
    try:
        if not _safe(folder, root) or not folder.is_dir():
            return []
        if not _safe(folder / 'METADATA', root):
            return []
        metadata = Parser().parsestr((folder / 'METADATA').read_text('utf-8'))
        name, version = metadata.get('Name', ''), metadata.get('Version', '')
        if (_project(name) not in projects or not version
                or _project(folder.name[:-10]) != _project(name + '-' + version)):
            return []
        record = folder / 'RECORD'
        if not _safe(record, root) or record.stat().st_size > 4_000_000:
            return []
        with record.open(encoding='utf-8', newline='') as stream:
            rows = {row[0]: row[1] for row in csv.reader(stream) if len(row) == 3}
        files = []
        for path in folder.rglob('*'):
            if not _safe(path, root):
                return []
            if not path.is_file():
                continue
            if path == record:
                continue
            key = path.relative_to(root / '_internal').as_posix()
            expected = rows.get(key, '')
            if not expected.startswith('sha256=') or path.stat().st_size > 4_000_000:
                return []
            actual = base64.urlsafe_b64encode(bytes.fromhex(_digest(path))).rstrip(b'=').decode('ascii')
            if expected != 'sha256=' + actual:
                return []
            files.append((path, _digest(path)))
        return files + [(record, _digest(record))]
    except (OSError, ValueError, UnicodeError, csv.Error):
        return []


def clean_installation(directory):
    root = Path(directory).resolve()
    internal = root / '_internal'
    if not all((root / name).is_file() for name in ('SocioLibrary.exe', 'unins000.exe', 'unins000.dat')):
        raise ValueError('Not an installed SocioLibrary program directory')
    manifest_path = root / 'bundle-manifest.json'
    if not _safe(manifest_path, root) or manifest_path.stat().st_size > 4_000_000:
        raise ValueError('Unsafe bundle manifest')
    manifest = json.loads(manifest_path.read_text('utf-8'))
    if manifest.get('schema') != 1 or not _safe(internal, root):
        raise ValueError('Unsupported bundle manifest or redirected runtime')
    pruned = manifest.get('pruned', [])
    current = manifest.get('metadata', [])
    if not isinstance(pruned, list) or len(pruned) > 30000 or not isinstance(current, list):
        raise ValueError('Invalid bundle manifest')
    projects = {_project(name[:-10].rsplit('-', 1)[0]) for name in current
                if isinstance(name, str) and re.fullmatch(r'[a-zA-Z0-9_.+\-]+\.dist-info', name)}
    report = {'version': manifest.get('version'), 'removed_files': 0, 'removed_bytes': 0,
              'removed_metadata': 0, 'preserved_files': 0, 'errors': 0}

    def remove(path, expected):
        try:
            if not path.exists():
                return
            if not _safe(path, root) or not path.is_file() or _digest(path) != expected:
                report['preserved_files'] += 1
                return
            size = path.stat().st_size
            path.unlink()
            report['removed_files'] += 1
            report['removed_bytes'] += size
            _remove_empty_parents(path.parent, internal)
        except OSError:
            report['errors'] += 1

    for entry in pruned:
        if not isinstance(entry, dict):
            raise ValueError('Invalid pruned file record')
        relative, digest = entry.get('path', ''), entry.get('sha256', '')
        # Only developer headers/CMake assets emitted by the build are eligible.
        if (not isinstance(relative, str) or '\\' in relative or '..' in relative.split('/')
                or not relative.startswith(('_internal/torch/include/', '_internal/torch/share/cmake/'))
                or not re.fullmatch('[a-f0-9]{64}', digest)):
            raise ValueError('Unsafe pruned file record')
        remove(root / relative, digest)
    for folder in internal.glob('*.dist-info'):
        if folder.name in current:
            continue
        files = _metadata_files(folder, root, projects)
        if files:
            for path, digest in files:
                remove(path, digest)
            if not folder.exists():
                report['removed_metadata'] += 1
    return report
