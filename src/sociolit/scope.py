"""Local, explicit Zotero collection selection for a smaller embedding pilot."""
import json

from .zotero import ZoteroClient


def resolve_scope(store, config):
    keywords = config.get("semantic", {}).get("collection_keywords", [])
    if not keywords:
        return None
    if not isinstance(keywords, list) or not all(isinstance(x, str) and x.strip() for x in keywords):
        raise ValueError("语义试点的文件夹关键词配置无效。")
    if store.state("import_incomplete", False):
        raise RuntimeError("文献导入尚未完成，请完成或继续导入后再建立语义索引。")
    settings = config.get("zotero", {})
    with ZoteroClient(base_url=settings.get("base_url", "http://127.0.0.1:23119/api"),
                      legacy_namespace=settings.get("library_name", "default")) as client:
        source, collections = client.collections()
    terms = [word.casefold().strip() for word in keywords]
    selected = {item["key"] for item in collections if any(word in item["name"].casefold() for word in terms)}
    if not selected:
        raise RuntimeError("没有找到匹配的 Zotero 文件夹，请检查本地试点配置。")
    while True:
        children = {item["key"] for item in collections if item["parent"] in selected}
        if children <= selected:
            break
        selected |= children
    with store.connect() as db:
        rows = db.execute("SELECT id,metadata FROM items WHERE source=?", (source,)).fetchall()
    included, parent_map = set(), {}
    for row in rows:
        item = json.loads(row["metadata"])
        raw = item.get("raw", {})
        if selected.intersection(raw.get("collections", [])):
            included.add(row["id"])
        parent = raw.get("parentItem")
        if parent:
            parent_map[row["id"]] = source + ":" + str(parent)
    # Include notes and standalone children of selected records, if present.
    while True:
        children = {item for item, parent in parent_map.items() if parent in included}
        if children <= included:
            break
        included |= children
    if not included:
        raise RuntimeError("已找到文件夹，但本地知识库没有对应条目；请先同步 Zotero。")
    return {"item_ids": sorted(included), "label": "、".join(keywords),
            "generation": store.state("import_generation", 0)}


def active_scope(store, config):
    if store.state("import_incomplete", False):
        raise RuntimeError("文献导入尚未完成，请完成导入后再使用语义检索。")
    if not config.get("semantic", {}).get("collection_keywords", []):
        return None
    scope = store.state("semantic_scope")
    if not scope or scope.get("label") != "、".join(config["semantic"]["collection_keywords"]):
        raise RuntimeError("请先构建所选文件夹的语义索引。")
    if scope.get("generation") != store.state("import_generation", 0):
        raise RuntimeError("Zotero 文献已更新，请重新构建试点语义索引。")
    return scope
