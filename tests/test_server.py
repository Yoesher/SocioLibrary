import pytest
from fastapi.testclient import TestClient
from filelock import FileLock

from sociolit.server import create_app
from sociolit.store import Store


@pytest.fixture
def app_client(tmp_path):
    root = tmp_path / "pdfs"
    root.mkdir()
    store = Store(tmp_path / "state")
    app = create_app(store, {"zotero": {"allowed_roots": [str(root)]}})
    with TestClient(app, base_url="http://localhost") as client:
        yield client, store, root


def _file(store, path, key="file"):
    with store.connect() as db:
        db.execute("INSERT OR IGNORE INTO items VALUES(?,?,?,?,?,?,?)",
                   ("paper", "synthetic", "paper", "Synthetic paper", "article", "{}", "test"))
        db.execute("INSERT INTO files VALUES(?,?,?,?,?,?)",
                   (key, "paper", str(path), "test", "indexed", ""))


@pytest.mark.parametrize("route", ["import", "embed", "discover", "search"])
def test_mutations_and_search_require_local_session_token(app_client, route):
    client, _, _ = app_client
    response = client.post("/api/" + route, json={"query": "care", "mode": "fulltext"})
    assert response.status_code == 403
    assert client.post("/api/" + route, headers={"X-Sociolit-Token": "forged"},
                       json={"query": "care", "mode": "fulltext"}).status_code == 403


def test_valid_token_cannot_bypass_origin_guard(app_client, monkeypatch):
    client, _, _ = app_client
    calls = []
    monkeypatch.setattr("sociolit.server.sync_zotero", lambda *_: calls.append(1) or {"ok": True})
    token = client.get("/api/status").json()["token"]
    headers = {"X-Sociolit-Token": token, "Origin": "https://untrusted.example"}
    assert client.post("/api/import", headers=headers).status_code == 403
    assert not calls
    headers["Origin"] = "http://localhost"
    assert client.post("/api/import", headers=headers).status_code == 200
    assert calls == [1]


@pytest.mark.parametrize("host", ["untrusted.example", "testserver"])
def test_foreign_host_cannot_read_status_or_token(app_client, host):
    client, _, _ = app_client
    response = client.get("/api/status", headers={"Host": host})
    assert response.status_code == 400
    assert "token" not in response.text


def test_private_responses_are_not_cacheable(app_client):
    client, _, _ = app_client
    response = client.get("/api/status")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert "access-control-allow-origin" not in response.headers


def test_pdf_serves_only_registered_files_inside_allowed_roots(app_client, tmp_path):
    client, store, root = app_client
    inside = root / "synthetic.pdf"
    inside.write_bytes(b"%PDF-1.4\n% synthetic endpoint fixture\n")
    outside = tmp_path / "private.pdf"
    outside.write_bytes(b"outside private fixture")
    _file(store, inside, "inside")
    _file(store, outside, "outside")
    response = client.get("/api/pdf/inside")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content == inside.read_bytes()
    assert client.get("/api/pdf/outside").status_code == 403
    assert client.get("/api/pdf/not-registered").status_code == 404
    assert client.get("/api/pdf/../../private.pdf").status_code == 404


def test_pdf_endpoint_rechecks_extension_and_file_existence(app_client):
    client, store, root = app_client
    text = root / "secret.txt"
    text.write_text("not a PDF", encoding="utf-8")
    _file(store, text, "wrong-type")
    _file(store, root / "moved.pdf", "missing")
    assert client.get("/api/pdf/wrong-type").status_code == 403
    assert client.get("/api/pdf/missing").status_code == 404


def test_search_returns_page_locator_without_local_path(app_client):
    client, store, root = app_client
    _file(store, root / "paper.pdf", "source:ABC12345")
    with store.connect() as db:
        store.add_chunk(db, item_id="paper", file_id="source:ABC12345", page=4,
                        page_label="17", kind="pdf", text="care work employment", ordinal=0)
    token = client.get("/api/status").json()["token"]
    response = client.post("/api/search", headers={"X-Sociolit-Token": token},
                           json={"query": "care", "mode": "fulltext"})
    assert response.status_code == 200
    row = response.json()[0]
    assert row["pdf_url"].endswith("#page=4")
    assert row["page_label"] == "17"
    assert "path" not in row and "source" not in row
    assert str(root) not in response.text


def test_busy_library_is_visible_and_prevents_a_second_model_load(app_client):
    client, store, _ = app_client
    token = client.get("/api/status").json()["token"]
    with FileLock(str(store.directory / "library.lock")):
        assert client.get("/api/status").json()["library_busy"] is True
        response = client.post("/api/embed", headers={"X-Sociolit-Token": token})
        assert response.status_code == 400
        assert "正在构建" in response.json()["detail"]
    assert client.get("/api/status").json()["library_busy"] is False


def test_full_issues_report_escapes_titles_and_hides_paths(app_client):
    client, store, root = app_client
    _file(store, root / "private.pdf", "issue-file")
    with store.connect() as db:
        db.execute("UPDATE items SET title=? WHERE id='paper'", ("<script>synthetic</script>",))
        db.execute("UPDATE files SET status='missing',detail='missing' WHERE id='issue-file'")
    response = client.get("/api/files/issues")
    assert response.status_code == 200
    assert "&lt;script&gt;synthetic&lt;/script&gt;" in response.text
    assert "<script>synthetic</script>" not in response.text
    assert str(root) not in response.text and "未下载" in response.text
