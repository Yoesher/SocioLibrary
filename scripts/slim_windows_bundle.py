"""Prune development-only files in a freshly generated Windows distribution."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def prune(root, version):
    root = Path(root).resolve()
    before = [(p, p.stat().st_size) for p in root.rglob('*') if p.is_file()]
    removed = []
    for relative in ('_internal/torch/include', '_internal/torch/share/cmake'):
        folder = root / relative
        if folder.is_symlink() or not folder.resolve().is_relative_to(root):
            raise ValueError('Unexpected developer directory link')
        if not folder.exists():
            continue
        for path in folder.rglob('*'):
            if not path.is_file():
                continue
            if path.is_symlink() or not path.resolve().is_relative_to(folder.resolve()):
                raise ValueError('Unexpected developer file link')
            if any(word in path.name.lower() for word in ('license', 'copying', 'notice')):
                continue
            with path.open('rb') as stream:
                digest = hashlib.file_digest(stream, 'sha256').hexdigest()
            removed.append({'path': path.relative_to(root).as_posix(), 'sha256': digest,
                            'bytes': path.stat().st_size})
            path.unlink()
        for directory in sorted(folder.rglob('*'), key=lambda p: len(p.parts), reverse=True) + [folder]:
            if directory.is_dir():
                try:
                    directory.rmdir()
                except OSError:
                    pass
    metadata = sorted(p.name for p in (root / '_internal').glob('*.dist-info') if p.is_dir())
    manifest = {'schema': 1, 'version': version, 'metadata': metadata, 'pruned': removed}
    (root / 'bundle-manifest.json').write_text(json.dumps(manifest, separators=(',', ':')), encoding='utf-8')
    after = [(p, p.stat().st_size) for p in root.rglob('*') if p.is_file()]
    report = {'version': version, 'before_bytes': sum(n for p, n in before), 'before_files': len(before),
              'after_bytes': sum(n for p, n in after), 'after_files': len(after),
              'removed_bytes': sum(e['bytes'] for e in removed), 'removed_files': len(removed)}
    return report


if __name__ == '__main__':
    root = ROOT / 'dist/SocioLibrary'
    if root.is_symlink() or root.resolve().parent != (ROOT / 'dist').resolve() or not (root / 'SocioLibrary.exe').is_file():
        raise SystemExit('Only a fresh dist/SocioLibrary build may be pruned')
    import tomllib
    version = tomllib.loads((ROOT / 'pyproject.toml').read_text('utf-8'))['project']['version']
    report = prune(root, version)
    (ROOT / 'build/bundle-size.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report))
