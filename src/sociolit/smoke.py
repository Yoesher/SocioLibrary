"""Synthetic data used only by the isolated packaged-application smoke test."""
import json
import sqlite3
from pathlib import Path

from . import research
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
    preferences = {"pdf_roots": [str(directory.resolve())], "collection_keywords": ["生育演示"]}
    (directory / "preferences.json").write_text(json.dumps(preferences, ensure_ascii=False), encoding="utf-8")
    model = directory / "models" / "e5-small"
    model.mkdir(parents=True)
    (model / "synthetic-model.txt").write_text("Synthetic model placeholder; not real model weights.", encoding="utf-8")
    (directory / "desktop-version.json").write_text(json.dumps({"version": "0.3.0"}), encoding="utf-8")


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
    marker = json.loads((directory / "desktop-version.json").read_text(encoding="utf-8"))
    assert marker["previous_version"] == "0.3.0" and marker["inherited"]
    with sqlite3.connect(directory / marker["backup"] / "library.sqlite3") as db:
        assert db.execute("SELECT body FROM reading_notes").fetchone()[0] == "Synthetic note survives upgrade"
        assert db.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    return {"data_inherited": True, "snapshot_verified": True, "from_version": "0.3.0"}
