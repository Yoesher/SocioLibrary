import threading
import time

import pytest
from fastapi.testclient import TestClient

from sociolit.indexing import import_snapshot
from sociolit.jobs import Jobs
from sociolit.preferences import apply_preferences, save_preferences
from sociolit.retrieval import reciprocal_rank_fusion
from sociolit.server import create_app
from sociolit.store import Store
from sociolit.zotero import Snapshot


def test_background_job_returns_before_work_finishes_and_rejects_overlap():
    entered, finish = threading.Event(), threading.Event()
    jobs = Jobs()
    def run(progress):
        progress("pdf_index", 2, 5)
        entered.set()
        assert finish.wait(3)
        return {"ok": True}
    jobs.start("import", run)
    assert entered.wait(1)
    assert jobs.snapshot()["done"] == 2
    with pytest.raises(RuntimeError):
        jobs.start("embed", run)
    finish.set()
    for _ in range(100):
        if jobs.snapshot()["state"] != "running":
            break
        time.sleep(.01)
    assert jobs.snapshot()["state"] == "done"
    assert jobs.snapshot()["result"]["ok"]


def test_preferences_are_persistent_and_invalid_root_cannot_replace_them(tmp_path):
    root = tmp_path / "papers"
    root.mkdir()
    config = {}
    save_preferences(config, tmp_path, [str(root)], ["生育"])
    assert apply_preferences({}, tmp_path)["zotero"]["allowed_roots"] == [str(root)]
    previous = (tmp_path / "preferences.json").read_bytes()
    for value in ("relative", str(tmp_path / "missing"), str(tmp_path.anchor), "//server/share"):
        with pytest.raises(ValueError):
            save_preferences(config, tmp_path, [value], [])
        assert (tmp_path / "preferences.json").read_bytes() == previous


def test_rank_fusion_rewards_agreement_without_comparing_score_scales():
    a, b, c = ({"id": i, "score": -100 if i == 1 else .99} for i in (1, 2, 3))
    rows = reciprocal_rank_fusion([a, b], [c, b])
    assert rows[0]["id"] == 2
    assert len(rows) == 3


def test_author_year_filter_happens_before_search_limit_and_results_include_sources(tmp_path):
    store = Store(tmp_path)
    items = [{"key": str(i), "title": "Care paper", "authors": ["Author A" if i < 110 else "Author B"],
              "year": "2024" if i < 110 else "2025", "tags": [], "abstract": "care evidence"} for i in range(111)]
    import_snapshot(store, Snapshot("zotero:synthetic", items, [], True))
    with TestClient(create_app(store, {}), base_url="http://localhost") as client:
        token = client.get("/api/status").json()["token"]
        rows = client.post("/api/search", headers={"X-Sociolit-Token": token},
                           json={"query": "care", "author": "Author B", "year": "2025"}).json()
        assert rows and all(r["item_key"] == "110" for r in rows)
        assert rows[0]["authors"] == ["Author B"]
        assert rows[0]["year"] == "2025"
        assert client.post("/api/preferences", json={"pdf_roots": []}).status_code == 403


def test_background_errors_are_visible_and_unknown_tasks_fail(tmp_path, monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("Synthetic failure")
    monkeypatch.setattr("sociolit.server.sync_zotero", fail)
    app = create_app(Store(tmp_path), {})
    with TestClient(app, base_url="http://localhost") as client:
        headers = {"X-Sociolit-Token": client.get("/api/status").json()["token"]}
        assert client.post("/api/jobs/unknown", headers=headers).status_code == 404
        assert client.post("/api/jobs/import", headers=headers).status_code == 200
        for _ in range(100):
            state = client.get("/api/status").json()["job"]
            if state["state"] != "running":
                break
            time.sleep(.01)
        assert state["state"] == "error"
        assert "Synthetic failure" in state["error"]
