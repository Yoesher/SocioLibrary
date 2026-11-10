"""Shorten only third-party notice filenames in an existing Windows build."""
import hashlib
import json
from pathlib import Path

root = Path("dist/SocioLibrary/third-party-licenses").resolve()
if not root.is_dir():
    raise SystemExit("No packaged dependency license directory")
index = {}
for source in list(root.rglob("*")):
    if not source.is_file() or len(source.name) <= 64:
        continue
    original = source.relative_to(root).as_posix()
    digest = hashlib.sha256(original.encode()).hexdigest()[:12]
    target = source.with_name(digest + "-" + source.name[-48:])
    if target.exists():
        raise SystemExit("License filename collision")
    source.rename(target)
    index[target.relative_to(root).as_posix()] = original
(root / "original-paths.json").write_text(json.dumps(index, indent=2), encoding="utf-8")
