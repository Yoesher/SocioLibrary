import json
import sqlite3
import time

from fastapi.testclient import TestClient

from sociolit import research
from sociolit.indexing import import_snapshot
from sociolit.server import create_app
from sociolit.store import Store
from sociolit.zotero import Snapshot


def library(tmp_path):
    store = Store(tmp_path)
    import_snapshot(
        store,
        Snapshot(
            "synthetic",
            [
                {
                    "key": "care",
                    "title": "Care evidence",
                    "authors": ["Synthetic Author"],
                    "year": "2024",
                    "abstract": "family care evidence",
                    "tags": [],
                }
            ],
            [],
            True,
        ),
    )
    research.initialize(store)
    return store


def test_reading_status_favorites_archive_restore_and_snapshot_survive_sync_deletion(tmp_path):
    store = library(tmp_path)
    original = store.stats()
    research.mark_reading(store, "synthetic:care", "reading", True)
    assert store.stats() == original
    assert research.reading_states(store, ["synthetic:care"])["synthetic:care"] == {
        "status": "reading",
        "favorite": True,
    }
    with store.connect() as db:
        db.execute("DELETE FROM items")
    row = research.reading_list(store, "reading", True)[0]
    assert not row["available"] and row["title"] == "Care evidence"
    research.mark_reading(store, row["item_id"], "done", True, archived=True)
    assert not research.reading_list(store)
    assert research.reading_list(store, archived=True)[0]["status"] == "done"
    research.mark_reading(store, row["item_id"], "done", True)
    assert research.reading_list(store)[0]["metadata"]["authors"] == ["Synthetic Author"]


def test_recent_queries_keep_conditions_deduplicate_and_limit_twenty(tmp_path):
    store = library(tmp_path)
    for i in range(25):
        research.remember_search(store, {"query": str(i), "mode": "fulltext", "author": "", "year": ""})
    query = {"query": "23", "mode": "fulltext", "author": "", "year": ""}
    research.remember_search(store, query)
    recent = research.recent_searches(store)
    assert len(recent) == 20 and recent[0] == query and sum(r == query for r in recent) == 1
    query["author"] = "Another author"
    research.remember_search(store, query)
    assert research.recent_searches(store)[0]["author"] == "Another author"


def test_optional_history_does_not_block_fulltext_when_an_index_writer_is_busy(tmp_path):
    store = library(tmp_path)
    with TestClient(create_app(store, {}), base_url="http://localhost") as client:
        headers = {"X-Sociolit-Token": client.get("/api/status").json()["token"]}
        writer = sqlite3.connect(store.path)
        try:
            writer.execute("BEGIN IMMEDIATE")
            start = time.monotonic()
            response = client.post("/api/search", headers=headers, json={"query": "care"})
            assert response.status_code == 200 and response.json()
            assert time.monotonic() - start < 2
        finally:
            writer.rollback()
            writer.close()


def test_export_includes_all_active_notes_beyond_ui_limit_and_preserves_page_and_ocr_warning(tmp_path):
    store = library(tmp_path)
    with store.connect() as db:
        db.executemany(
            "INSERT INTO reading_notes VALUES(?,?,?,?,?,?)",
            [
                (
                    str(i),
                    "Synthetic note " + str(i),
                    "literal body ````\n<script>not executed</script>",
                    json.dumps(
                        {
                            "title": "Synthetic source",
                            "page": 7,
                            "page_label": "ix",
                            "kind": "ocr",
                            "text": "original quote",
                        }
                    ),
                    "2026-11-10",
                    int(i == 504),
                )
                for i in range(505)
            ],
        )
    assert len(research.list_records(store, "notes")) == 500
    output = "".join(research.notes_markdown(store))
    assert output.count("## Synthetic note ") == 504
    assert "PDF 第 7 页" in output and "页标签：ix" in output and "OCR 识别摘录" in output
    assert "`````text\n" in output and "## Synthetic note 504\n" not in output


def test_reading_and_recent_route_behavior_and_source_database_remain_unchanged(tmp_path):
    store = library(tmp_path)
    with TestClient(create_app(store, {}), base_url="http://localhost") as client:
        headers = {"X-Sociolit-Token": client.get("/api/status").json()["token"]}
        body = {"item_id": "synthetic:care", "status": "to_read", "favorite": True}
        assert client.post("/api/research/reading", json=body).status_code == 403
        assert client.post("/api/research/reading", json=body, headers=headers).status_code == 200
        results = client.post("/api/search", json={"query": "care"}, headers=headers).json()
        assert results[0]["reading"]["favorite"]
        assert client.get("/api/research/recent", headers=headers).json()[0]["query"] == "care"
        assert client.post("/api/research/recent/clear", headers=headers).status_code == 200
        assert not client.get("/api/research/recent", headers=headers).json()
        assert client.get("/api/research/reading?favorite=true", headers=headers).json()[0]["favorite"]
        assert (
            client.post(
                "/api/research/reading", headers=headers, json=dict(body, status="invalid")
            ).status_code
            == 400
        )
        assert store.stats()["items"] == 1
