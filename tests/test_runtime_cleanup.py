import base64
import csv
import hashlib
import io
import json

import pytest

from scripts.slim_windows_bundle import prune
from sociolit.runtime_cleanup import clean_installation


def installed(tmp_path):
    root = tmp_path / 'program'
    root.mkdir()
    (root / '_internal').mkdir()
    for name in ('SocioLibrary.exe', 'unins000.exe', 'unins000.dat'):
        (root / name).write_bytes(b'Synthetic program file')
    return root


def metadata(root, name, version, extra=False):
    folder = root / '_internal' / f'{name}-{version}.dist-info'
    folder.mkdir()
    (folder / 'METADATA').write_text(f'Name: {name}\nVersion: {version}\n', encoding='utf-8')
    (folder / 'WHEEL').write_text('Synthetic wheel', encoding='utf-8')
    rows = []
    for path in folder.iterdir():
        body = path.read_bytes()
        digest = base64.urlsafe_b64encode(hashlib.sha256(body).digest()).rstrip(b'=').decode('ascii')
        rows.append([path.relative_to(root / '_internal').as_posix(), 'sha256=' + digest, len(body)])
    rows.append([folder.name + '/RECORD', '', ''])
    with (folder / 'RECORD').open('w', encoding='utf-8', newline='') as stream:
        csv.writer(stream).writerows(rows)
    if extra:
        (folder / 'private-notes.txt').write_text('Synthetic user content', encoding='utf-8')
    return folder


def manifest(root, pruned=(), current=('fastapi-1.0.dist-info',)):
    (root / 'bundle-manifest.json').write_text(json.dumps({'schema': 1, 'version': '0.12.3',
        'metadata': list(current), 'pruned': list(pruned)}), encoding='utf-8')


def test_build_prunes_developer_files_keeps_runtime_and_license_and_emits_hashes(tmp_path):
    root = installed(tmp_path)
    header = root / '_internal/torch/include/synthetic.h'
    header.parent.mkdir(parents=True)
    header.write_text('Synthetic developer header', encoding='utf-8')
    (header.parent / 'LICENSE').write_text('Synthetic license', encoding='utf-8')
    library = root / '_internal/torch/lib/torch_cpu.dll'
    library.parent.mkdir()
    library.write_bytes(b'Synthetic runtime library')
    metadata(root, 'fastapi', '1.0')
    report = prune(root, '0.12.3')
    value = json.loads((root / 'bundle-manifest.json').read_text('utf-8'))
    assert not header.exists() and library.is_file() and (header.parent / 'LICENSE').is_file()
    assert value['pruned'][0]['sha256'] == hashlib.sha256(b'Synthetic developer header').hexdigest()
    assert report['removed_files'] == 1 and report['removed_bytes'] == len(b'Synthetic developer header')
    assert value['metadata'] == ['fastapi-1.0.dist-info']


def test_upgrade_cleanup_only_removes_hash_matched_headers_and_verified_old_metadata(tmp_path):
    root = installed(tmp_path)
    folder = root / '_internal/torch/include'
    folder.mkdir(parents=True)
    header = folder / 'original.h'
    header.write_bytes(b'original')
    modified = folder / 'modified.h'
    modified.write_bytes(b'user modified header')
    private = folder / 'research.pdf'
    private.write_bytes(b'Synthetic private PDF canary')
    old = metadata(root, 'fastapi', '0.9')
    current = metadata(root, 'fastapi', '1.0')
    unknown = metadata(root, 'private_plugin', '0.1')
    rows = [{'path': path.relative_to(root).as_posix(), 'sha256': hashlib.sha256(b'original').hexdigest()}
            for path in (header, modified)]
    manifest(root, rows)
    report = clean_installation(root)
    assert not header.exists() and not old.exists()
    assert current.exists() and unknown.exists() and private.read_bytes() == b'Synthetic private PDF canary'
    assert modified.read_bytes() == b'user modified header'
    assert report['removed_metadata'] == 1 and report['preserved_files'] == 1 and not report['errors']
    assert clean_installation(root)['removed_files'] == 0


@pytest.mark.parametrize('damage', ['changed_file', 'unrecorded_file', 'corrupt_record'])
def test_unverified_or_user_modified_metadata_is_preserved(tmp_path, damage):
    root = installed(tmp_path)
    old = metadata(root, 'fastapi', '0.9', extra=damage == 'unrecorded_file')
    if damage == 'changed_file':
        (old / 'METADATA').write_text('Name: fastapi\nVersion: 0.9\nCustom: changed\n', encoding='utf-8')
    if damage == 'corrupt_record':
        (old / 'RECORD').write_text('invalid,record', encoding='utf-8')
    before = {p.name: p.read_bytes() for p in old.iterdir()}
    manifest(root)
    assert clean_installation(root)['removed_metadata'] == 0
    assert {p.name: p.read_bytes() for p in old.iterdir()} == before


@pytest.mark.parametrize('relative', ['../library.sqlite3', '_internal/torch/include/../../../library.sqlite3',
                                      '_internal/torch/lib/torch_cpu.dll', '_internal\\torch\\include\\a.h'])
def test_manifest_cannot_authorize_deletion_outside_development_files(tmp_path, relative):
    root = installed(tmp_path)
    data = tmp_path / 'library.sqlite3'
    data.write_bytes(b'Synthetic private data')
    manifest(root, [{'path': relative, 'sha256': hashlib.sha256(data.read_bytes()).hexdigest()}])
    with pytest.raises(ValueError, match='Unsafe pruned'):
        clean_installation(root)
    assert data.read_bytes() == b'Synthetic private data'


def test_redirected_header_tree_never_deletes_external_files(tmp_path):
    root = installed(tmp_path)
    data = tmp_path / 'private'
    data.mkdir()
    paper = data / 'original.h'
    paper.write_bytes(b'Synthetic private data')
    folder = root / '_internal/torch'
    folder.mkdir()
    link = folder / 'include'
    try:
        link.symlink_to(data, target_is_directory=True)
    except OSError:
        pytest.skip('Windows developer-mode symlink permission unavailable')
    manifest(root, [{'path': '_internal/torch/include/original.h', 'sha256': hashlib.sha256(paper.read_bytes()).hexdigest()}])
    assert clean_installation(root)['removed_files'] == 0
    assert paper.read_bytes() == b'Synthetic private data'


def test_cleanup_refuses_a_research_folder_without_installation_identity(tmp_path):
    (tmp_path / 'library.sqlite3').write_bytes(b'Synthetic private data')
    with pytest.raises(ValueError, match='Not an installed'):
        clean_installation(tmp_path)


def test_record_cannot_redirect_cleanup_to_an_outside_path(tmp_path):
    root = installed(tmp_path)
    old = metadata(root, 'fastapi', '0.9')
    outside = tmp_path / 'private.txt'
    outside.write_text('Synthetic private data')
    content = io.StringIO((old / 'RECORD').read_text('utf-8'))
    rows = list(csv.reader(content)) + [['../../private.txt', '', '']]
    with (old / 'RECORD').open('w', encoding='utf-8', newline='') as stream:
        csv.writer(stream).writerows(rows)
    manifest(root)
    clean_installation(root)
    assert outside.read_text() == 'Synthetic private data'
