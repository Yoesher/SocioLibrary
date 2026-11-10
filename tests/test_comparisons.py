import copy
import csv
import io
import json
import sys
import threading
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from sociolit import comparisons
from sociolit.ai import Profiles
from sociolit.ai_context import AIWorkspace, fingerprint
from sociolit.comparison_ai import ComparisonAI
from sociolit.desktop import DesktopAPI
from sociolit.indexing import import_snapshot
from sociolit.server import create_app
from sociolit.store import Store
from sociolit.zotero import Snapshot


@pytest.fixture
def matrix(tmp_path):
    store = Store(tmp_path / "data")
    import_snapshot(store, Snapshot("synthetic", [
        {"key": "A", "title": "生育与就业退出", "authors": ["Synthetic A"], "abstract": "照料约束"},
        {"key": "B", "title": "家庭照料与劳动供给", "authors": ["Synthetic B"], "abstract": "制度解释"}], [], True))
    comparisons.initialize(store)
    with store.connect() as db:
        rows = db.execute("SELECT * FROM chunks ORDER BY item_id").fetchall()
        sources = [{"chunk_id": row["id"], "digest": fingerprint(row)} for row in rows]
    board = comparisons.create(store, "合成文献对照", sources)
    return store, board, sources


def test_manual_matrix_revision_archive_and_source_deletion_retention(matrix):
    store, board, sources = matrix
    assert len(board["papers"]) == 2 and set(board["cells"]["P1"]) == set(comparisons.FIELDS)
    cells = copy.deepcopy(board["cells"])
    cells["P1"]["question"] = {"text": "就业退出如何发生？", "citations": ["S1"], "reviewed": True}
    saved = comparisons.save(store, board["id"], board["revision"], "已编辑", cells)
    assert saved["revision"] != board["revision"]
    with pytest.raises(ValueError, match="变化"):
        comparisons.save(store, board["id"], board["revision"], "stale", board["cells"])
    archived = comparisons.archive(store, saved["id"], saved["revision"], True)
    assert comparisons.list_boards(store) == []
    restored = comparisons.archive(store, archived["id"], archived["revision"], False)
    with store.connect() as db:
        db.execute("DELETE FROM items")
    frozen = comparisons.get(store, restored["id"])
    assert frozen["cells"]["P1"]["question"]["text"] == "就业退出如何发生？"
    assert all(not source["current"] and source["pdf_url"] is None for source in frozen["sources"])
    assert frozen["sources"][0]["text"] == board["sources"][0]["text"]
    assert "就业退出" in comparisons.export(store, frozen["id"], "md")


def test_matrix_requires_distinct_papers_current_evidence_and_matching_citations(matrix):
    store, board, sources = matrix
    with pytest.raises(ValueError, match="2–6"):
        comparisons.create(store, "one paper", [sources[0]])
    changed = [{**sources[0], "digest": "0" * 64}, sources[1]]
    with pytest.raises(RuntimeError, match="变化"):
        comparisons.create(store, "invalid", changed)
    cells = copy.deepcopy(board["cells"])
    cells["P1"]["data"]["citations"] = ["S2"]
    with pytest.raises(ValueError, match="另一篇"):
        comparisons.save(store, board["id"], board["revision"], "invalid", cells)
    assert len(comparisons.list_boards(store)) == 1


def test_csv_formula_protection_and_markdown_preserve_literal_text(matrix):
    store, board, _ = matrix
    cells = copy.deepcopy(board["cells"])
    cells["P1"]["question"]["text"] = '=HYPERLINK("https://example.org")'
    cells["P2"]["limits"]["text"] = '<script>bad()</script> | [link](file:///private)\nnext'
    saved = comparisons.save(store, board["id"], board["revision"], "=unsafe-title", cells)
    values = list(csv.reader(io.StringIO(comparisons.export(store, saved["id"], "csv"))))
    assert values[1][0] == "'=unsafe-title" and values[1][5].startswith("'=HYPERLINK")
    text = comparisons.export(store, saved["id"], "md")
    assert "<script>" not in text and "&lt;script&gt;" in text
    assert "\\|" in text and "\\[link\\]" in text and "来源快照" in text
    with pytest.raises(ValueError, match="变化"):
        comparisons.export(store, saved["id"], "csv", board["revision"])


def generated(board):
    return {paper["code"]: {key: {"text": "有来源的合成归纳", "citations": [next(source["label"]
                for source in board["sources"] if source["paper"] == paper["code"])]} for key in comparisons.FIELDS}
            for paper in board["papers"]}


@pytest.mark.parametrize("damage", ["json", "unknown_source", "other_paper", "missing_field", "no_evidence", "duplicate_key"])
def test_invalid_ai_matrix_is_rejected_without_changing_original(matrix, damage):
    store, board, _ = matrix
    values = generated(board)
    if damage == "unknown_source":
        values["P1"]["question"]["citations"] = ["S99"]
    elif damage == "other_paper":
        values["P1"]["question"]["citations"] = ["S2"]
    elif damage == "missing_field":
        del values["P1"]["question"]
    elif damage == "no_evidence":
        values["P1"]["question"]["citations"] = []
    text = json.dumps(values)
    if damage == "json":
        text = "not a JSON table"
    elif damage == "duplicate_key":
        text = '{"P1":{},' + text[1:]
    with pytest.raises(ValueError):
        comparisons.parse_ai(text, board)
    assert comparisons.get(store, board["id"])["revision"] == board["revision"]


def make_ai(store, board):
    profiles = Profiles(store.directory)
    identity = profiles.save(identity=None, name="合成本机连接", protocol="responses", base_url="http://127.0.0.1:11434/v1",
                             model="synthetic-model", max_output_tokens=2048)["id"]
    seen = []

    def handle(request):
        seen.append(request)
        return httpx.Response(200, json={"status": "completed", "output": [{"type": "message", "content": [
            {"type": "output_text", "text": json.dumps(generated(board), ensure_ascii=False)}]}],
            "usage": {"input_tokens": 100, "output_tokens": 100}})
    workspace = AIWorkspace(store, profiles, factory=lambda: httpx.Client(transport=httpx.MockTransport(handle)))
    return ComparisonAI(store, workspace), workspace, identity, seen


def test_ai_preview_one_request_and_adoption_is_a_separate_unreviewed_copy(matrix):
    store, board, _ = matrix
    ai, _, profile, seen = make_ai(store, board)
    preview = ai.prepare(board["id"], profile, "比较解释路径")
    assert not seen and "synthetic:A" not in preview["prompt"]
    result = ai.ask(preview["confirmation"])
    assert len(seen) == 1 and len(comparisons.list_boards(store)) == 1
    payload = json.loads(seen[0].content)
    assert payload["input"] == preview["prompt"] and payload["store"] is False
    saved = ai.adopt(result["id"])
    assert saved["id"] != board["id"] and saved["origin"] == "ai_draft"
    assert not saved["cells"]["P1"]["question"]["reviewed"]
    assert comparisons.get(store, board["id"])["cells"] == board["cells"]
    with pytest.raises(RuntimeError, match="已使用"):
        ai.ask(preview["confirmation"])
    with pytest.raises(RuntimeError, match="已使用"):
        ai.adopt(result["id"])
    assert len(seen) == 1


@pytest.mark.parametrize("change", ["source", "board", "profile"])
def test_changed_comparison_context_stops_before_transmission(matrix, change):
    store, board, _ = matrix
    ai, workspace, profile, seen = make_ai(store, board)
    preview = ai.prepare(board["id"], profile)
    if change == "source":
        with store.connect() as db:
            db.execute("UPDATE chunks SET text='changed'")
    elif change == "board":
        comparisons.save(store, board["id"], board["revision"], "changed", board["cells"])
    else:
        workspace.profiles.save(identity=profile, name="changed", protocol="responses", base_url="http://127.0.0.1:11434/v1",
                                model="different-model", max_output_tokens=2048)
    with pytest.raises(RuntimeError, match="变化"):
        ai.ask(preview["confirmation"])
    assert not seen


def test_matrix_routes_require_session_origin_and_cost_consent(matrix):
    store, board, _ = matrix
    _, workspace, profile, seen = make_ai(store, board)
    app = create_app(store, {}, ai_workspace=workspace)
    with TestClient(app, base_url="http://localhost") as client:
        assert client.get("/api/comparisons").status_code == 403
        assert client.get("/api/comparisons/" + board["id"]).status_code == 403
        assert client.get("/api/annotations").status_code == 403
        headers = {"X-Sociolit-Token": client.get("/api/status").json()["token"]}
        assert client.post("/api/literature/recommend", headers=headers, json={"item_id": "synthetic:A"}).status_code == 200
        body = {"identity": board["id"], "profile_id": profile}
        preview = client.post("/api/ai/comparison/preview", headers=headers, json=body).json()
        assert not seen
        confirmation = {"confirmation": preview["confirmation"]}
        assert client.post("/api/ai/comparison/ask", headers=headers, json=confirmation).status_code == 400
        assert client.post("/api/ai/comparison/ask", headers={**headers, "Origin": "https://foreign.example"},
                           json={**confirmation, "consent": True}).status_code == 403
        app.state.maintenance.set()
        assert client.post("/api/ai/comparison/ask", headers=headers, json={**confirmation, "consent": True}).status_code == 409
        assert not seen


def test_native_csv_export_writes_bom_and_checks_version_without_altering_library(matrix, tmp_path, monkeypatch):
    store, board, _ = matrix
    target = tmp_path / "export.csv"
    monkeypatch.setitem(sys.modules, "webview", SimpleNamespace(SAVE_DIALOG=1))
    bridge = DesktopAPI()
    bridge._store, bridge._directory, bridge._native_lock = store, store.directory, threading.Lock()
    bridge._window = SimpleNamespace(create_file_dialog=lambda *args, **kwargs: [str(target)])
    assert bridge.export_comparison(board["id"], "csv", board["revision"])["saved"]
    assert target.read_bytes().startswith(b"\xef\xbb\xbf")
    assert "来源编号" in target.read_text(encoding="utf-8-sig")
    with pytest.raises(ValueError):
        bridge.export_comparison(board["id"], "csv", "0" * 32)
    assert comparisons.get(store, board["id"])["revision"] == board["revision"]
