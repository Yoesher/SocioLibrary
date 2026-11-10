"""Include installed dependency notices in the Windows binary distribution."""
import importlib.metadata
from pathlib import Path

output = Path("dist/SocioLibrary/third-party-licenses")
output.mkdir(parents=True, exist_ok=True)
for distribution in importlib.metadata.distributions():
    name = distribution.metadata["Name"]
    safe = "".join(c for c in name if c.isalnum() or c in "-_.")
    folder = output / safe
    folder.mkdir(exist_ok=True)
    details = [f"Name: {name}", f"Version: {distribution.version}",
               f"License: {distribution.metadata.get('License-Expression') or distribution.metadata.get('License', 'See distribution notices')}"]
    (folder / "metadata.txt").write_text("\n".join(details), encoding="utf-8")
    for relative in distribution.files or []:
        if any(word in relative.name.lower() for word in ("license", "copying", "notice")):
            source = Path(distribution.locate_file(relative))
            if source.is_file() and source.stat().st_size < 2_000_000:
                filename = "_".join(relative.parts).replace(":", "_")
                (folder / filename).write_bytes(source.read_bytes())
