from .config import allowed_roots
from .indexing import import_snapshot
from .zotero import ZoteroClient, load_export


def sync_zotero(store, config, export=None, progress=None):
    roots = allowed_roots(config)
    if export:
        snapshot = load_export(export, allowed_roots=roots)
    else:
        settings = config.get("zotero", {})
        with ZoteroClient(base_url=settings.get("base_url", "http://127.0.0.1:23119/api"),
                          allowed_roots=roots, legacy_namespace=settings.get("library_name", "default"),
                          progress=progress) as client:
            snapshot = client.snapshot()
    return import_snapshot(store, snapshot, progress=progress)


def build_configured_embeddings(store, config, embedder, progress=None):
    from .scope import resolve_scope
    from .semantic import build_vectors

    if store.state("import_incomplete", False):
        raise RuntimeError("文献导入尚未完成，请完成导入后再建立语义索引。")
    scope = resolve_scope(store, config)
    store.set_state("semantic_scope", scope)
    count = build_vectors(store, embedder, item_ids=scope["item_ids"] if scope else None, progress=progress)
    if scope and scope["generation"] != store.state("import_generation", 0):
        raise RuntimeError("构建时文献库发生变化；请重新构建语义索引。")
    return {"indexed": count, "scope": scope["label"] if scope else "全部文献",
            "items": len(scope["item_ids"]) if scope else None}
