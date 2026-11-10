import json

import httpx
import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter

from sociolit import annotations, research
from sociolit.indexing import import_snapshot
from sociolit.server import create_app
from sociolit.store import Store
from sociolit.zotero import Attachment, Snapshot, ZoteroClient, ZoteroError


def annotation(text="生育照料摘录", comment="<b>个人评论</b>", page=2):
    return {"key": "ANNO0001", "itemType": "annotation", "parentItem": "ATTACH01", "annotationType": "highlight",
            "annotationText": text, "annotationComment": comment, "annotationColor": "#ffd400",
            "annotationPageLabel": "ii", "annotationPosition": json.dumps({"pageIndex": page}),
            "tags": [{"tag": "照料"}]}


@pytest.fixture
def imported(tmp_path):
    pdf = tmp_path / "synthetic.pdf"
    writer = PdfWriter()
    for _ in range(3):
        writer.add_blank_page(width=300, height=300)
    with pdf.open("wb") as stream:
        writer.write(stream)
    items = [{"key": "PAPER001", "title": "合成生育文献", "item_type": "journalArticle", "authors": ["Synthetic"]}]
    attachments = [Attachment("ATTACH01", "PAPER001", pdf)]
    data = annotations.normalize(annotation(), "ANNO0001", {"ATTACH01": {"parentItem": "PAPER001"}})
    snapshot = Snapshot("zotero:synthetic", items, attachments, True, annotations=[data])
    store = Store(tmp_path / "data")
    research.initialize(store)
    import_snapshot(store, snapshot)
    return store, snapshot, pdf


def test_local_api_reads_annotation_fields_without_external_requests_or_writes(tmp_path):
    pdf = tmp_path / "synthetic.pdf"
    pdf.write_bytes(b"synthetic path fixture")
    records = [{"key": "PAPER001", "data": {"itemType": "journalArticle", "title": "合成"}},
               {"key": "ATTACH01", "data": {"itemType": "attachment", "parentItem": "PAPER001", "contentType": "application/pdf"}},
               {"key": "ANNO0001", "data": annotation(text="p < 0.01") }]
    seen = []

    def handle(request):
        seen.append(request)
        assert request.method == "GET" and request.url.host == "127.0.0.1"
        headers = {"Zotero-Server-ID": "synthetic", "Last-Modified-Version": "1", "Total-Results": "3"}
        if request.url.path.endswith("/file/view/url"):
            return httpx.Response(200, text=pdf.as_uri())
        return httpx.Response(200, json={} if request.url.params.get("format") == "versions" else records, headers=headers)

    with ZoteroClient(allowed_roots=[tmp_path], transport=httpx.MockTransport(handle)) as client:
        result = client.snapshot()
    assert len(result.items) == 1 and len(result.annotations) == 1
    record = result.annotations[0]
    assert record["text"] == "p < 0.01" and record["comment"] == "个人评论"
    assert record["page"] == 3 and record["page_label"] == "ii"
    assert record["parent_key"] == "PAPER001" and record["color"] == "#ffd400"
    assert seen[-1].url.params["format"] == "versions"


@pytest.mark.parametrize("page", [None, -1, "3", True, 3000])
def test_page_label_never_invents_physical_pdf_page(page):
    data = annotations.normalize(annotation(page=page), "ANNO0001", {"ATTACH01": {"parentItem": "PAPER001"}})
    assert data["page"] is None and data["page_label"] == "ii"


def test_incremental_annotation_index_updates_and_preserves_independent_note(imported):
    store, snapshot, _ = imported
    matches = [row for row in store.search("生育照料") if row["kind"] == "annotation"]
    assert len(matches) == 1 and matches[0]["page"] == 3
    record = annotations.records(store)["records"][0]
    title, body, source = annotations.note_snapshot(store, record["id"], record["revision"])
    note = research.save_note(store, title, body, source)
    chunk = matches[0]["id"]
    with store.connect() as db:
        db.execute("INSERT INTO vectors VALUES(?,?,?)", (chunk, "synthetic-model", "[1,0]"))
    stats = import_snapshot(store, snapshot)
    assert stats["annotations"]["changed"] == 0 and stats["files_unchanged"] == 1
    assert [row for row in store.search("生育照料") if row["kind"] == "annotation"][0]["id"] == chunk
    snapshot.annotations[0]["comment"] = "修改后的个人意见"
    import_snapshot(store, snapshot)
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM vectors").fetchone()[0] == 0
        assert "个人评论" in db.execute("SELECT body FROM reading_notes WHERE id=?", (note,)).fetchone()[0]
    assert annotations.records(store)["records"][0]["comment"] == "修改后的个人意见"
    with pytest.raises(ValueError, match="变化"):
        annotations.note_snapshot(store, record["id"], record["revision"])


def test_missing_or_deleted_source_retains_snapshot_but_removes_stale_search_entries(imported):
    store, snapshot, _ = imported
    snapshot.annotations = []
    import_snapshot(store, snapshot)
    assert annotations.records(store)["total"] == 0
    retained = annotations.records(store, include_missing=True)
    assert retained["total"] == 1 and not retained["records"][0]["current"]
    assert retained["records"][0]["text"] == "生育照料摘录" and retained["records"][0]["pdf_url"] is None
    assert not [row for row in store.search("生育照料") if row["kind"] == "annotation"]
    snapshot.items, snapshot.attachments = [], []
    import_snapshot(store, snapshot)
    assert annotations.records(store, include_missing=True)["total"] == 1


def test_pdf_replacement_rebuilds_annotation_chunks_without_losing_snapshot(imported):
    store, snapshot, pdf = imported
    pdf.write_bytes(pdf.read_bytes() + b"\n% synthetic changed file\n")
    import_snapshot(store, snapshot)
    assert annotations.records(store)["total"] == 1
    matches = [row for row in store.search("生育照料") if row["kind"] == "annotation"]
    with store.connect() as db:
        assert len(matches) == 1
        assert db.execute("SELECT chunk_id FROM annotation_chunks").fetchone()[0] == matches[0]["id"]


def test_incomplete_snapshot_cannot_modify_annotations(imported):
    store, snapshot, _ = imported
    before = annotations.records(store, include_missing=True)
    snapshot.complete, snapshot.annotations = False, []
    with pytest.raises(ValueError, match="Incomplete"):
        import_snapshot(store, snapshot)
    assert annotations.records(store, include_missing=True) == before


def test_long_annotation_is_flagged_and_note_never_silently_truncates(imported):
    store, snapshot, _ = imported
    snapshot.annotations[0]["text"] = "材料" * 7000
    snapshot.annotations[0]["comment"] = "评论" * 7000
    import_snapshot(store, snapshot)
    row = annotations.records(store)["records"][0]
    with pytest.raises(ValueError, match="较长"):
        annotations.note_snapshot(store, row["id"], row["revision"])
    data = annotations.normalize(annotation(text="x" * 20001), "ANNO0001", {"ATTACH01": {"parentItem": "PAPER001"}})
    assert data["truncated"] and len(data["text"]) == 20000


def test_single_page_api_change_is_detected_before_import():
    def handle(request):
        final = request.url.params.get("format") == "versions"
        return httpx.Response(200, json=[] if final else [{"key": "PAPER001", "data": {"itemType": "book"}}],
            headers={"Zotero-Server-ID": "synthetic", "Last-Modified-Version": "2" if final else "1", "Total-Results": "1"})
    with ZoteroClient(transport=httpx.MockTransport(handle)) as client, pytest.raises(ZoteroError, match="变化"):
        client.snapshot()


@pytest.mark.parametrize("case", ["unavailable_pdf", "unknown_page"])
def test_missing_pdf_or_unknown_page_never_creates_fake_reader_link(imported, case):
    store, snapshot, pdf = imported
    if case == "unavailable_pdf":
        snapshot.attachments[0].path = None
        snapshot.attachments[0].warning = "Synthetic unavailable PDF"
    else:
        snapshot.annotations[0]["page"] = None
    import_snapshot(store, snapshot)
    assert annotations.records(store)["records"][0]["pdf_url"] is None
    app = create_app(store, {"zotero": {"allowed_roots": [str(pdf.parent)]}})
    with TestClient(app, base_url="http://localhost") as client:
        token = client.get("/api/status").json()["token"]
        rows = client.post("/api/search", json={"query": "生育照料"}, headers={"X-Sociolit-Token": token}).json()
        assert rows and all(row["pdf_url"] is None for row in rows if row["kind"] == "annotation")
