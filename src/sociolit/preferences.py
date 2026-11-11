"""Explicit local user preferences, separate from installation files."""
import json
import os
from pathlib import Path


def apply_preferences(config, directory):
    path = Path(directory) / "preferences.json"
    if path.exists():
        settings = json.loads(path.read_text(encoding="utf-8"))
        config.setdefault("zotero", {})["allowed_roots"] = settings["pdf_roots"]
        config.setdefault("semantic", {})["collection_keywords"] = settings.get("collection_keywords", [])
    return config


def save_preferences(config, directory, roots, keywords):
    clean = []
    for value in roots:
        if not value.strip() or value.startswith(("\\\\", "//")):
            raise ValueError("请选择本机的 PDF 文件夹，不支持网络共享。")
        path = Path(value).expanduser()
        if not path.is_absolute() or not path.is_dir():
            raise ValueError("PDF 文件夹不存在，或不是绝对路径。")
        path = path.resolve()
        if path == Path(path.anchor):
            raise ValueError("请选择 Zotero storage 等具体文件夹，不要选择整个磁盘。")
        if str(path) not in clean:
            clean.append(str(path))
    path = Path(directory) / "preferences.json"
    settings = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if not isinstance(settings, dict):
        raise ValueError("本机设置格式无效，未覆盖。")
    settings.update(pdf_roots=clean, collection_keywords=[x.strip() for x in keywords if x.strip()])
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)
    return apply_preferences(config, directory)
