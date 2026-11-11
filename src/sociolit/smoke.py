"""Synthetic data used only by the isolated packaged-application smoke test."""
import json
import sqlite3
from pathlib import Path

from . import annotations as annotation_records
from . import comparisons, research
from .ai import Profiles
from .ocr import initialize as initialize_ocr
from .store import Store


def seed_upgrade_fixture(directory):
    directory = Path(directory)
    if (directory / "library.sqlite3").exists():
        raise RuntimeError("Synthetic upgrade fixture requires a new isolated folder")
    store = Store(directory)
    research.initialize(store)
    initialize_ocr(store)
    with store.connect() as db:
        db.execute("INSERT INTO items VALUES(?,?,?,?,?,?,?)", ("synthetic:item", "synthetic", "item",
                   "Synthetic upgrade paper", "journalArticle", json.dumps({"authors": ["Synthetic"], "year": "2020"}), "fixture"))
        db.execute("INSERT INTO files VALUES(?,?,?,?,?,?)", ("synthetic:file", "synthetic:item",
                   str(directory / "synthetic.pdf"), "synthetic-hash", "needs_ocr", "Synthetic fixture"))
        store.add_chunk(db, item_id="synthetic:item", text="synthetic upgrade evidence", kind="ocr",
                        file_id="synthetic:file", page=1, page_label="1")
        chunk = db.execute("SELECT id FROM chunks").fetchone()[0]
        db.execute("INSERT INTO vectors VALUES(?,?,?)", (chunk, "synthetic-model", "[0.1,0.2]"))
        db.execute("INSERT INTO ocr_pages VALUES(?,?,?,?)", ("synthetic:file", 1, "en-US", "synthetic upgrade evidence"))
    store.set_state("semantic_scope", {"label": "生育演示", "generation": 0, "item_ids": ["synthetic:item"]})
    store.set_state("journal-feed:人口学刊", {"url": "https://example.org/synthetic-feed", "enabled": False})
    research.save_search(store, "Synthetic saved search", {"query": "upgrade", "mode": "fulltext", "author": "", "year": ""})
    research.save_note(store, "Synthetic reading note", "Synthetic note survives upgrade", {"text": "synthetic excerpt", "page": 1})
    preferences = {"pdf_roots": [str(directory.resolve())], "collection_keywords": ["生育演示"],
                   "theme": "ink", "motion": "quick", "density": "compact", "auto_embed": False}
    (directory / "preferences.json").write_text(json.dumps(preferences, ensure_ascii=False), encoding="utf-8")
    model = directory / "models" / "e5-small"
    model.mkdir(parents=True)
    (model / "synthetic-model.txt").write_text("Synthetic model placeholder; not real model weights.", encoding="utf-8")
    (directory / "desktop-version.json").write_text(json.dumps({"version": "0.3.0"}), encoding="utf-8")
    if __import__("os").name == "nt":
        Profiles(directory).save(identity=None, name="Synthetic AI connection", protocol="responses",
            base_url="https://api.openai.com/v1", model="synthetic-model", max_output_tokens=2048,
            api_key="synthetic-smoke-secret")
    _seed_reading_extensions(store)


def _seed_reading_extensions(store):
    from types import SimpleNamespace

    from .ai_context import fingerprint
    annotation_records.sync_snapshots(store, SimpleNamespace(source_id="synthetic", annotations=[
        {"key": "ANNOT001", "parent_key": "item", "attachment_key": "file", "type": "highlight",
         "text": "Retained synthetic annotation", "comment": "Synthetic comment", "page": 1,
         "page_label": "1", "color": "#ffd400", "tags": ["synthetic"], "truncated": False}]))
    annotation_records.sync_snapshots(store, SimpleNamespace(source_id="synthetic", annotations=[]))
    comparisons.initialize(store)
    # Create a valid two-paper matrix, then simulate one source being removed.
    with store.connect() as db:
        db.execute("INSERT INTO items VALUES(?,?,?,?,?,?,?)", ("synthetic:gone", "synthetic", "gone",
                   "Synthetic removed source", "journalArticle", "{}", "fixture"))
        store.add_chunk(db, item_id="synthetic:gone", text="Synthetic removed evidence", kind="metadata")
        rows = db.execute("SELECT * FROM chunks ORDER BY id").fetchall()
        selections = [{"chunk_id": row["id"], "digest": fingerprint(row)} for row in rows]
    board = comparisons.create(store, "Synthetic retained comparison", selections)
    board["cells"]["P1"]["question"] = {"text": "Retained synthetic comparison", "citations": ["S1"], "reviewed": True}
    comparisons.save(store, board["id"], board["revision"], board["title"], board["cells"])
    from . import graph
    graph.initialize(store)
    graph.create_link(store, "synthetic:item", "synthetic:gone", "theory", "Synthetic retained graph relation")
    from . import catalog_semantic
    catalog_semantic.initialize(store)
    with store.connect() as db:
        row = db.execute("SELECT title,metadata FROM items WHERE id='synthetic:item'").fetchone()
        db.execute("INSERT INTO catalog_vectors VALUES(?,?,?,?)", ("synthetic:item", "synthetic-catalog",
                   catalog_semantic.fingerprint(catalog_semantic.content(row)), "[1.0,0.0]"))
    with store.connect() as db:
        db.execute("DELETE FROM items WHERE id='synthetic:gone'")


def check_upgrade_fixture(directory, store):
    directory = Path(directory)
    assert store.stats() == {"items": 1, "files": 1, "chunks": 1, "vectors": 1}
    assert store.search("upgrade")[0]["page"] == 1
    assert research.list_records(store, "notes")[0]["body"] == "Synthetic note survives upgrade"
    assert research.list_records(store, "searches")[0]["name"] == "Synthetic saved search"
    assert store.state("journal-feed:人口学刊")["enabled"] is False
    with store.connect() as db:
        assert db.execute("SELECT text FROM ocr_pages").fetchone()[0] == "synthetic upgrade evidence"
    assert (directory / "models/e5-small/synthetic-model.txt").read_text(encoding="utf-8").startswith("Synthetic model")
    preferences = json.loads((directory / "preferences.json").read_text(encoding="utf-8"))
    assert preferences["collection_keywords"] == ["生育演示"]
    assert preferences["theme"] == "ink" and preferences["motion"] == "quick"
    assert preferences["density"] == "compact" and preferences["auto_embed"] is False
    marker = json.loads((directory / "desktop-version.json").read_text(encoding="utf-8"))
    assert marker["previous_version"] == "0.3.0" and marker["inherited"]
    with sqlite3.connect(directory / marker["backup"] / "library.sqlite3") as db:
        assert db.execute("SELECT body FROM reading_notes").fetchone()[0] == "Synthetic note survives upgrade"
        assert db.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    if __import__("os").name == "nt":
        profiles = Profiles(directory)
        identity = profiles.list()["profiles"][0]["id"]
        assert profiles.key(profiles.get(identity)) == "synthetic-smoke-secret"
        assert (directory / marker["backup"] / "ai-profiles.json").read_bytes() == profiles.path.read_bytes()
    retained = annotation_records.records(store, include_missing=True)
    assert retained["records"][0]["text"] == "Retained synthetic annotation"
    board = comparisons.get(store, comparisons.list_boards(store)[0]["id"])
    assert board["cells"]["P1"]["question"]["text"] == "Retained synthetic comparison"
    assert not board["sources"][1]["current"]
    with sqlite3.connect(directory / marker["backup"] / "library.sqlite3") as db:
        assert db.execute("SELECT count(*) FROM zotero_annotations").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM literature_comparisons").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM literature_links").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM catalog_vectors").fetchone()[0] == 1
    from . import graph
    network = graph.build(store, seed="synthetic:item", include_auto=False)
    assert len(network["edges"]) == 1 and any(not node["current"] for node in network["nodes"])
    return {"data_inherited": True, "snapshot_verified": True, "from_version": "0.3.0",
            "comparison_inherited": True, "annotation_snapshot_inherited": True,
            "graph_inherited": True, "appearance_inherited": True, "catalog_index_inherited": True}
