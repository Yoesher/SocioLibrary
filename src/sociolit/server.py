import json
import secrets
import threading
from hashlib import sha256
from html import escape
from pathlib import Path
from urllib.parse import quote, urlparse

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from filelock import FileLock, Timeout
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .config import allowed_roots
from .jobs import Jobs
from .preferences import apply_preferences, save_preferences
from .scope import active_scope
from .semantic import LocalEmbedder, search_vectors
from .service import build_configured_embeddings, sync_zotero


class Query(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    mode: str = "fulltext"
    author: str = Field(default="", max_length=100)
    year: str = Field(default="", max_length=4)


class Preferences(BaseModel):
    pdf_roots: list[str] = Field(max_length=20)
    collection_keywords: list[str] = Field(default_factory=list, max_length=30)


def create_app(store, config):
    apply_preferences(config, store.directory)
    app = FastAPI(title="SocioLibrary", docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "[::1]"])
    token = secrets.token_urlsafe(32)
    operation_lock = threading.Lock()
    jobs = Jobs()
    app.state.jobs = jobs
    static = Path(__file__).parent / "static"
    model_path = config.get("semantic", {}).get("model_path") or store.directory / "models" / "e5-small"
    embedder_cache = []
    embedder_lock = threading.Lock()

    def embedder():
        with embedder_lock:
            if not embedder_cache:
                embedder_cache.append(LocalEmbedder(model_path))
        return embedder_cache[0]

    @app.middleware("http")
    async def guard(request: Request, call_next):
        if request.method not in ("GET", "HEAD"):
            origin = request.headers.get("origin")
            if origin and urlparse(origin).netloc != request.headers.get("host"):
                from fastapi.responses import JSONResponse
                return JSONResponse({"detail": "Foreign origin blocked"}, status_code=403)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        return response

    def authorize(value):
        if not value or not secrets.compare_digest(value, token):
            raise HTTPException(403, "Local session token required")

    def mutate(function):
        if not operation_lock.acquire(blocking=False):
            raise HTTPException(409, "Another indexing/update operation is running")
        try:
            return function()
        except (RuntimeError, ValueError, OSError) as exc:
            raise HTTPException(400, str(exc)) from exc
        finally:
            operation_lock.release()

    def ensure_library_available():
        try:
            with FileLock(str(store.directory / "library.lock"), timeout=0.1):
                pass
        except Timeout as exc:
            raise RuntimeError("文献或语义索引正在构建，请等待当前任务完成。") from exc

    @app.get("/")
    def home():
        return FileResponse(static / "index.html")

    @app.get("/api/status")
    def status():
        try:
            with FileLock(str(store.directory / "library.lock"), timeout=0):
                library_busy = False
        except Timeout:
            library_busy = True
        with store.connect() as db:
            problems = [dict(r) for r in db.execute("""SELECT i.title,f.status,f.detail FROM files f
                JOIN items i ON i.id=f.item_id WHERE f.detail != '' LIMIT 10""")]
            problem_count = db.execute("SELECT COUNT(*) FROM files WHERE detail != ''").fetchone()[0]
        last_import = store.state("last_import")
        if isinstance(last_import, dict):
            last_import = {k: v for k, v in last_import.items() if k != "warnings"}
        scope = store.state("semantic_scope")
        scope_label = "、".join(config.get("semantic", {}).get("collection_keywords", []))
        scope_progress = None
        manifest = Path(model_path) / "sociolit-model.json"
        if isinstance(scope, dict) and scope.get("label") == scope_label and scope.get("item_ids") and manifest.is_file():
            model_key = sha256(manifest.read_bytes()).hexdigest()
            with store.connect() as db:
                db.execute("CREATE TEMP TABLE scope_items(id TEXT PRIMARY KEY)")
                db.executemany("INSERT INTO scope_items VALUES(?)", [(item,) for item in scope["item_ids"]])
                total = db.execute("SELECT count(*) FROM chunks c JOIN scope_items s ON s.id=c.item_id").fetchone()[0]
                done = db.execute("""SELECT count(*) FROM vectors v JOIN chunks c ON c.id=v.chunk_id
                    JOIN scope_items s ON s.id=c.item_id WHERE v.model=?""", (model_key,)).fetchone()[0]
                scope_progress = {"done": done, "total": total}
        journals = []
        for journal in config.get("journals", []):
            homepage = journal.get("homepage", "")
            try:
                parsed = urlparse(homepage)
                if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
                    homepage = ""
            except ValueError:
                homepage = ""
            journals.append({"name": journal.get("name"), "enabled": journal.get("enabled", False), "homepage": homepage, "status": journal.get("status", "")})
        return {"stats": store.stats(), "token": token, "last_import": last_import,
                "import_incomplete": store.state("import_incomplete", False),
                "discovery": store.state("last_discovery"), "file_notices": problems, "file_notice_count": problem_count,
                "pdf_roots_configured": bool(allowed_roots(config)), "semantic_model_ready": (Path(model_path) / "sociolit-model.json").is_file(),
                "semantic_scope": scope_label, "semantic_progress": scope_progress, "library_busy": library_busy,
                "journals": journals, "job": jobs.snapshot(), "version": __import__("sociolit").__version__,
                "pdf_roots": [str(p) for p in allowed_roots(config)],
                "collection_keywords": config.get("semantic", {}).get("collection_keywords", [])}

    @app.post("/api/zotero/check")
    def check_zotero(x_sociolit_token: str | None = Header(default=None)):
        authorize(x_sociolit_token)
        from .zotero import ZoteroClient
        try:
            with ZoteroClient() as client:
                response = client._get("/users/0/items?format=json&limit=1")
            if not isinstance(response.json(), list):
                raise ValueError("Unrecognized Zotero response")
            return {"connected": True}
        except (RuntimeError, ValueError, OSError) as exc:
            raise HTTPException(400, "未连接到 Zotero。请打开 Zotero，并在设置 → 高级中允许本机应用通信。") from exc

    @app.post("/api/preferences")
    def preferences(body: Preferences, x_sociolit_token: str | None = Header(default=None)):
        authorize(x_sociolit_token)
        def save():
            if jobs.snapshot()["state"] == "running":
                raise RuntimeError("请等待后台任务完成后再修改设置。")
            ensure_library_available()
            save_preferences(config, store.directory, body.pdf_roots, body.collection_keywords)
            return {"saved": True}
        return mutate(save)

    @app.post("/api/jobs/{action}")
    def start_job(action: str, x_sociolit_token: str | None = Header(default=None)):
        authorize(x_sociolit_token)
        from .scheduler import discover_due
        from .semantic import prepare_model
        actions = {
            "import": lambda progress: mutate(lambda: sync_zotero(store, config, progress=progress)),
            "embed": lambda progress: mutate(lambda: build_configured_embeddings(store, config, embedder(), progress=progress)),
            "discover": lambda progress: mutate(lambda: discover_due(store, config, force=True)),
            "model": lambda progress: mutate(lambda: prepare_model(model_path)),
        }
        if action not in actions:
            raise HTTPException(404, "Unknown task")
        try:
            ensure_library_available()
            return jobs.start(action, actions[action])
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/api/import")
    def sync(x_sociolit_token: str | None = Header(default=None)):
        authorize(x_sociolit_token)
        return mutate(lambda: sync_zotero(store, config))

    @app.post("/api/embed")
    def embed(x_sociolit_token: str | None = Header(default=None)):
        authorize(x_sociolit_token)
        def run():
            ensure_library_available()
            return build_configured_embeddings(store, config, embedder())
        return mutate(run)

    @app.post("/api/discover")
    def discover(x_sociolit_token: str | None = Header(default=None)):
        authorize(x_sociolit_token)
        from .scheduler import discover_due
        return mutate(lambda: discover_due(store, config, force=True))

    @app.post("/api/search")
    def search(body: Query, x_sociolit_token: str | None = Header(default=None)):
        authorize(x_sociolit_token)
        try:
            selected = None
            if body.author or body.year:
                with store.connect() as db:
                    records = db.execute("""SELECT id FROM items
                        WHERE instr(lower(COALESCE(json_extract(metadata,'$.authors'),'')),lower(?)) > 0
                        AND (? = '' OR CAST(json_extract(metadata,'$.year') AS TEXT) = ?)""",
                        (body.author, body.year, body.year)).fetchall()
                selected = [record["id"] for record in records]
                if not selected:
                    return []
            if body.mode in ("semantic", "hybrid"):
                scope = active_scope(store, config)
                ensure_library_available()
                ids = scope["item_ids"] if scope else None
                if selected is not None:
                    ids = list(set(selected).intersection(ids)) if ids is not None else selected
                    if not ids:
                        return []
                semantic = search_vectors(store, embedder(), body.query, limit=100, item_ids=ids)
                if body.mode == "hybrid":
                    from .retrieval import reciprocal_rank_fusion
                    rows = reciprocal_rank_fusion(store.search(body.query, limit=100, item_ids=ids), semantic)
                else:
                    rows = semantic
            elif body.mode == "fulltext":
                rows = store.search(body.query, limit=100, item_ids=selected)
            else:
                raise ValueError("Unknown search mode")
            # Prevent a long paper from occupying the entire result list.
            counts, diverse = {}, []
            for row in rows:
                count = counts.get(row["item_id"], 0)
                if count < 3:
                    diverse.append(row)
                    counts[row["item_id"]] = count + 1
                if len(diverse) == 20:
                    break
            rows = diverse
            with store.connect() as db:
                for row in rows:
                    meta = json.loads(db.execute("SELECT metadata FROM items WHERE id=?", (row["item_id"],)).fetchone()[0])
                    row["authors"] = meta.get("authors", [])
                    row["year"] = str(meta.get("year", ""))
                    row["journal"] = (meta.get("raw") or {}).get("journal", "") if isinstance(meta.get("raw"), dict) else ""
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from exc
        for row in rows:
            row.pop("source", None)
            row["pdf_url"] = "/api/pdf/" + quote(row["file_id"], safe="") + "#page=" + str(row["page"]) if row["file_id"] else None
        return rows

    @app.get("/api/pdf/{file_id:path}")
    def pdf(file_id: str):
        with store.connect() as db:
            row = db.execute("SELECT path FROM files WHERE id=?", (file_id,)).fetchone()
        if not row or not row[0]:
            raise HTTPException(404, "PDF unavailable")
        path = Path(row[0]).resolve()
        if not any(path.is_relative_to(root) for root in allowed_roots(config)) or path.suffix.lower() != ".pdf":
            raise HTTPException(403, "PDF outside allowed roots")
        if not path.is_file():
            raise HTTPException(404, "PDF moved; sync Zotero again")
        return FileResponse(path, media_type="application/pdf", content_disposition_type="inline")

    @app.get("/api/discovery/report")
    def discovery_report():
        report = store.directory / "discovery" / "digests" / "digest.md"
        if not report.is_file():
            raise HTTPException(404, "尚无本地期刊更新报告；请先检查期刊更新。")
        return FileResponse(report, media_type="text/plain; charset=utf-8", content_disposition_type="inline")

    @app.get("/api/files/issues", response_class=HTMLResponse)
    def file_issues():
        with store.connect() as db:
            rows = db.execute("""SELECT i.title,f.status,f.detail FROM files f
                JOIN items i ON i.id=f.item_id WHERE f.detail != '' ORDER BY f.status,i.title""").fetchall()
        entries = []
        for row in rows:
            status, detail = row["status"], row["detail"]
            if status == "missing":
                message = "附件未下载、已移动或不在许可目录。"
            elif status == "needs_ocr":
                message = "没有检测到文字层，需要 OCR。"
            elif status == "error":
                message = "PDF 未能提取；可能超过大小或页数限制，也可能无法打开。"
            else:
                prefix = "No extractable text on PDF pages: "
                pages = detail.removeprefix(prefix) if detail.startswith(prefix) else ""
                message = "部分 PDF 页面没有检测到文字层。" + (" 页序：" + pages if pages else "")
            entries.append("<tr><td>" + escape(row["title"]) + "</td><td>" + escape(message) + "</td></tr>")
        body = "".join(entries) or '<tr><td colspan="2">暂无附件提示。</td></tr>'
        return HTMLResponse('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>附件提示 · SocioLibrary</title><link rel="stylesheet" href="/static/style.css"></head>'
            '<body><main><a href="/">← 返回知识库</a><h1>需要注意的附件</h1>'
            f'<p>共 {len(rows)} 份。缺失附件可在 Zotero 中下载后重新同步；扫描页需 OCR。</p>'
            '<table><thead><tr><th>文献</th><th>提示</th></tr></thead><tbody>' + body + '</tbody></table></main></body></html>')

    app.mount("/static", StaticFiles(directory=static), name="static")
    return app
