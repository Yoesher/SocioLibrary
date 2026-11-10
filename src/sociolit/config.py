import os
import tomllib
from pathlib import Path


def default_data_dir() -> Path:
    if os.environ.get("SOCIOLIT_DATA_DIR"):
        return Path(os.environ["SOCIOLIT_DATA_DIR"]).expanduser().resolve()
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local" / "share"))
    return base / "SocioLit"


def read_config(path: str | Path | None) -> dict:
    if path is None:
        return {}
    with Path(path).open("rb") as stream:
        return tomllib.load(stream)


def data_dir(config: dict, override: str | Path | None = None) -> Path:
    return Path(override or config.get("local", {}).get("data_dir") or default_data_dir()).expanduser().resolve()


def allowed_roots(config: dict) -> list[Path]:
    return [Path(p).expanduser().resolve() for p in config.get("zotero", {}).get("allowed_roots", [])]
