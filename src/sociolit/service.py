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


def refresh_after_sync(store, config, result, embedder, model_path, progress=None):
    """Only extend an established local pilot; never download or train implicitly."""
    from pathlib import Path

    from .appearance import read
    summary = {"sync": {key: value for key, value in result.items() if key != "warnings"}}
    summary["message"] = "同步完成。未自动更新语义索引；可在资料整理中建立全库书目索引或在设置中构建全文试点。"
    scope = store.state("semantic_scope")
    enabled = read(store.directory)["auto_embed"]
    if (enabled and scope and scope.get("item_ids")
            and config.get("semantic", {}).get("collection_keywords")
            and (Path(model_path) / "sociolit-model.json").is_file()):
        try:
            summary["semantic"] = build_configured_embeddings(store, config, embedder(), progress=progress)
            summary["message"] = "同步完成，当前语义试点已增量补齐。"
        except (RuntimeError, ValueError, OSError) as exc:
            summary["message"] = "同步已完成；语义更新尚未完成，可稍后继续：" + str(exc)[:300]
    if enabled and store.state("catalog_semantic") and (Path(model_path) / "sociolit-model.json").is_file():
        from .catalog_semantic import build
        try:
            summary["catalog"] = build(store, embedder(), progress)
            summary["message"] = (summary["message"] if "semantic" in summary or "尚未完成" in summary["message"] else "同步完成。") + " 全库书目语义已增量补齐。"
        except (RuntimeError, ValueError, OSError) as exc:
            summary["message"] += " 全库书目语义尚未补齐，可稍后继续：" + str(exc)[:200]
    store.set_state("workflow_summary", summary)
    return {**result, "workflow": summary}
