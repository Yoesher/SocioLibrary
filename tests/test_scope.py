import json
from unittest.mock import patch

import pytest

from sociolit.indexing import import_snapshot
from sociolit.scope import active_scope, resolve_scope
from sociolit.semantic import build_vectors, search_vectors
from sociolit.service import build_configured_embeddings
from sociolit.store import Store
from sociolit.zotero import Snapshot


class FakeClient:
    def __init__(self, **kwargs):
        pass
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass
    def collections(self):
        return "zotero:sample", [{"key":"A", "name":"生育研究", "parent":""},
                                  {"key":"B", "name":"家庭", "parent":"A"},
                                  {"key":"C", "name":"劳动", "parent":""}]


class Encoder:
    key = "test-model"
    def encode(self, texts, *, query=False):
        return [[1.0, 0.0] if "care" in x else [0.0, 1.0] for x in texts]


def item(key, title, collections=(), parent=None):
    return {"key":key, "title":title, "authors":[], "abstract":"", "tags":[],
            "raw":{"collections":list(collections), "parentItem":parent}}


def setup_store(tmp_path):
    store = Store(tmp_path)
    records = [item("A1", "care evidence", ["A"]), item("B1", "child topic", ["B"]),
               item("C1", "unrelated labor", ["C"]), item("N1", "child note", parent="A1")]
    import_snapshot(store, Snapshot("zotero:sample", records, [], True))
    return store


def test_collection_and_descendant_scope_search_only_selected(tmp_path):
    store = setup_store(tmp_path)
    config = {"semantic":{"collection_keywords":["生育"]}}
    with patch("sociolit.scope.ZoteroClient", FakeClient):
        scope = resolve_scope(store, config)
        assert set(scope["item_ids"]) == {"zotero:sample:A1", "zotero:sample:B1", "zotero:sample:N1"}
        result = build_configured_embeddings(store, config, Encoder())
    assert result["items"] == 3 and result["indexed"] == 3
    active = active_scope(store, config)
    results = search_vectors(store, Encoder(), "care", item_ids=active["item_ids"])
    assert len(results) == 3 and all(r["item_key"] != "C1" for r in results)
    assert results[0]["item_key"] == "A1"


def test_scope_invalidated_by_new_import_and_incomplete_import(tmp_path):
    store = setup_store(tmp_path)
    config = {"semantic":{"collection_keywords":["生育"]}}
    with patch("sociolit.scope.ZoteroClient", FakeClient):
        build_configured_embeddings(store, config, Encoder())
    store.set_state("import_incomplete", True)
    with pytest.raises(RuntimeError, match="尚未完成"):
        active_scope(store, config)
    store.set_state("import_incomplete", False)
    store.set_state("import_generation", store.state("import_generation") + 1)
    with pytest.raises(RuntimeError, match="已更新"):
        active_scope(store, config)


def test_partial_scope_requires_missing_vectors_to_be_built(tmp_path):
    store = setup_store(tmp_path)
    selected = ["zotero:sample:A1", "zotero:sample:B1"]
    assert build_vectors(store, Encoder(), item_ids=selected[:1]) == 1
    with pytest.raises(RuntimeError, match="尚未完成"):
        search_vectors(store, Encoder(), "care", item_ids=selected)
    assert build_vectors(store, Encoder(), item_ids=selected) == 1
    assert len(search_vectors(store, Encoder(), "care", item_ids=selected)) == 2


def test_no_matching_folders_and_empty_scope_fail_clearly(tmp_path):
    store = setup_store(tmp_path)
    with patch("sociolit.scope.ZoteroClient", FakeClient):
        with pytest.raises(RuntimeError, match="没有找到"):
            resolve_scope(store, {"semantic":{"collection_keywords":["不存在的目录"]}})
    with pytest.raises(ValueError, match="没有可索引"):
        build_vectors(store, Encoder(), item_ids=[])


def test_store_preserves_raw_collections_as_metadata(tmp_path):
    store = setup_store(tmp_path)
    with store.connect() as db:
        item_json = db.execute("SELECT metadata FROM items WHERE item_key='A1'").fetchone()[0]
    assert json.loads(item_json)["raw"]["collections"] == ["A"]
