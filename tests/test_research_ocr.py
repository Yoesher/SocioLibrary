import hashlib
from datetime import date

import httpx
import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter

from sociolit.discovery import DiscoveryResult, run_discovery
from sociolit.indexing import import_snapshot
from sociolit.ocr import process_ocr
from sociolit.server import create_app
from sociolit.store import Store
from sociolit.subscriptions import apply_feeds, configure_feed
from sociolit.zotero import Attachment, Snapshot


def fixture_library(tmp_path):
    root = tmp_path / "papers"
    root.mkdir()
    path = root / "scan.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.add_blank_page(width=200, height=200)
    with path.open("wb") as f:
        writer.write(f)
    store = Store(tmp_path / "state")
    item = dict(key="DEMO", title="Synthetic scanned paper", authors=["Sample"], year="2025", tags=[])
    snapshot = Snapshot("zotero:fixture", [item], [Attachment("FILE", "DEMO", path)], True)
    import_snapshot(store, snapshot)
    return store, root, path, snapshot


def test_ocr_keeps_original_resume_preserves_derived_text_on_sync_and_invalidates_changes(tmp_path):
    store, root, path, snapshot = fixture_library(tmp_path)
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    calls = []
    def recognize(image, language):
        assert image.is_file() and language == "en-US"
        calls.append(image)
        return "synthetic scanned care evidence"
    first = process_ocr(store, [root], "en-US", max_pages=1, recognizer=recognize)
    assert first["pages"] == 1 and first["may_have_more"]
    assert len(store.search("scanned care")) == 1
    assert store.search("scanned care")[0]["kind"] == "ocr"
    assert not calls[0].exists()  # temporary page image removed
    import_snapshot(store, snapshot)
    assert len(store.search("scanned care")) == 1
    assert process_ocr(store, [root], "en-US", recognizer=recognize)["pages"] == 1
    assert len(calls) == 2
    assert process_ocr(store, [root], "en-US", recognizer=recognize)["pages"] == 0
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    path.write_bytes(path.read_bytes() + b"\n% changed")
    with pytest.raises(RuntimeError, match="变化"):
        process_ocr(store, [root], "en-US", recognizer=recognize)
    import_snapshot(store, snapshot)
    assert not store.search("scanned care")
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM ocr_pages").fetchone()[0] == 0


def test_notes_survive_zotero_deletion_edits_and_archive_restore(tmp_path):
    store, root, _, _ = fixture_library(tmp_path)
    with TestClient(create_app(store, {"zotero": {"allowed_roots": [str(root)]}}), base_url="http://localhost") as client:
        headers = {"X-Sociolit-Token": client.get("/api/status").json()["token"]}
        assert client.get("/api/research").status_code == 403
        chunk = store.search("scanned")[0]
        response = client.post("/api/research/notes", headers=headers,
            json={"title": "My note", "body": "<script>not HTML</script>", "source_chunk_id": chunk["id"]})
        assert response.status_code == 200
        identity = response.json()["id"]
        import_snapshot(store, Snapshot("zotero:fixture", [], [], True))
        notes = client.get("/api/research", headers=headers).json()["notes"]
        assert notes[0]["source"]["title"] == "Synthetic scanned paper"
        assert notes[0]["body"].startswith("<script>")
        assert client.post("/api/research/notes", headers=headers,
            json={"id": identity, "title": "Revised", "body": "New thinking"}).status_code == 200
        for expected in (True, False):
            client.post(f"/api/research/notes/{identity}/archive", headers=headers)
            assert client.get("/api/research", headers=headers).json()["notes"][0]["archived"] is expected
        response = client.post("/api/research/searches", headers=headers,
            json={"name": "Care", "query": {"query": "care", "mode": "hybrid", "year": "2025", "author": "Sample"}})
        assert response.status_code == 200
        saved = client.get("/api/research", headers=headers).json()["searches"][0]
        assert saved["query"] == {"query": "care", "mode": "hybrid", "year": "2025", "author": "Sample"}


def test_failed_feed_cannot_enable_pending_journal_or_replace_previous(tmp_path):
    store = Store(tmp_path)
    config = {"journals": [{"name": "社会学评论", "issns": ["2095-5154"], "enabled": False, "sources": []}]}
    def success(*args, **kw):
        return DiscoveryResult()
    configure_feed(store, config, "社会学评论", "https://publisher.example/rss", runner=success)
    assert config["journals"][0]["enabled"]
    original = store.state("journal-feed:社会学评论")
    with pytest.raises(ValueError):
        configure_feed(store, config, "社会学评论", "https://publisher.example/bad", runner=lambda *a, **k: DiscoveryResult(errors=["403"]))
    assert store.state("journal-feed:社会学评论") == original
    with pytest.raises(ValueError):
        configure_feed(store, config, "社会学评论", "https://publisher.example/rss?token=secret", runner=success)
    other = {"journals": [{"name": "社会学评论"}]}
    assert apply_feeds(store, other)["journals"][0]["required_feed_title"] == "社会学评论"


def test_feed_title_mismatch_rejects_wrong_journal_without_network():
    for title, expected in (("社会学评论 当期目录", True), ("Another journal", False)):
        page = f'<rss version="2.0"><channel><title>{title}</title></channel></rss>'
        with httpx.Client(transport=httpx.MockTransport(lambda request, page=page: httpx.Response(200, text=page))) as client:
            from unittest.mock import patch
            with patch("sociolit.discovery._validate_feed_url"):
                result = run_discovery([dict(name="社会学评论", enabled=True, sources=["rss"],
                    required_feed_title="社会学评论", rss_url="https://publisher.example/rss")],
                    date(2026,1,1), date(2026,11,10), client=client, sleep=lambda _: None)
        assert result.complete is expected


def test_ocr_cjk_spacing_is_searchable(tmp_path):
    store, root, _, _ = fixture_library(tmp_path)
    process_ocr(store, [root], "zh-Hans-CN", recognizer=lambda *_: "家 庭 照 料 影 响 就 业")
    assert store.search("家庭照料")
