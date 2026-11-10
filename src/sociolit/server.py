import json
import secrets
import threading
from hashlib import sha256
from html import escape
from pathlib import Path
from urllib.parse import quote, urlparse

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from filelock import FileLock, Timeout
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import research
from .ai_routes import attach_ai
from .config import allowed_roots
from .jobs import Jobs
from .literature_routes import attach_literature
from .ocr import initialize as initialize_ocr
from .ocr import process_ocr, windows_ocr
from .preferences import apply_preferences, save_preferences
from .scope import active_scope
from .semantic import LocalEmbedder, search_vectors
from .service import build_configured_embeddings, sync_zotero
from .software_updates import UpdateError, UpdateManager
from .subscriptions import apply_feeds, configure_feed
from .upgrades import upgrade_status


class Query(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    mode: str = "fulltext"
    author: str = Field(default="", max_length=100)
    year: str = Field(default="", max_length=4)


class Preferences(BaseModel):
    pdf_roots: list[str] = Field(max_length=20)
    collection_keywords: list[str] = Field(default_factory=list, max_length=30)


class SavedSearch(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    query: Query


class ReadingNote(BaseModel):
    id: str | None = Field(default=None, max_length=64)
    title: str = Field(min_length=1, max_length=300)
    body: str = Field(min_length=1, max_length=20000)
    source_chunk_id: int | None = None
    source_digest: str = Field(default="", max_length=64)


class FeedSettings(BaseModel):
    name: str = Field(max_length=100)
    url: str = Field(max_length=2000)
    enabled: bool = True


class OCRSettings(BaseModel):
    language: str = Field(default="zh-Hans-CN", max_length=30, pattern=r"^[a-zA-Z0-9-]+$")
    max_pages: int = Field(default=20, ge=1, le=100)


class AutomaticUpdate(BaseModel):
    enabled: bool


class ReadingSetting(BaseModel):
    item_id: str = Field(min_length=1, max_length=1000)
    status: str = Field(default="to_read", max_length=20)
    favorite: bool = False
    archived: bool = False


def chunk_digest(row):
    values = [row[k] for k in ("id", "item_id", "file_id", "page", "text")]
    return sha256(json.dumps(values, ensure_ascii=False).encode()).hexdigest()


def create_app(store, config, *, updater=None, ai_workspace=None):
    research.initialize(store)
    initialize_ocr(store)
    apply_feeds(store, config)
    apply_preferences(config, store.directory)
    app = FastAPI(title="SocioLibrary", docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "[::1]"])
    token = secrets.token_urlsafe(32)
    operation_lock = threading.Lock()
    jobs = Jobs()
    app.state.jobs = jobs
    app.state.operation_lock = operation_lock
    app.state.maintenance = threading.Event()
    app.state.updater = updater or UpdateManager(store.directory, __import__("sociolit").__version__)
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
            if app.state.maintenance.is_set():
                from fastapi.responses import JSONResponse
                return JSONResponse({"detail": "软件正在准备升级，请等待安装完成。"}, status_code=409)
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

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        # Pydantic errors normally echo invalid inputs, which may contain an API key.
        if request.url.path.startswith("/api/ai/"):
            from fastapi.responses import JSONResponse
            return JSONResponse({"detail": "AI 设置或请求格式无效，请检查必填项和长度。"}, status_code=422)
        return await request_validation_exception_handler(request, exc)

    attach_ai(app, store, authorize, mutate, workspace=ai_workspace)
    attach_literature(app, store, config, authorize, mutate, embedder)

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
            problems = [dict(r) for r in db.execute("""SELECT i.title,f.status,f.detail,
                (SELECT count(*) FROM ocr_pages op WHERE op.file_id=f.id) AS ocr_pages FROM files f
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
                "collection_keywords": config.get("semantic", {}).get("collection_keywords", []),
                "ocr_pages": store.state("ocr_summary", {}).get("pages", 0), "upgrade": upgrade_status(store.directory),
                "software_update": app.state.updater.snapshot()}

    @app.post("/api/software-update/check")
    def check_update(x_sociolit_token: str | None = Header(default=None)):
        authorize(x_sociolit_token)
        try:
            return app.state.updater.check()
        except UpdateError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/api/software-update/download")
    def download_update(x_sociolit_token: str | None = Header(default=None)):
        authorize(x_sociolit_token)
        try:
            return app.state.updater.download()
        except UpdateError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/api/software-update/automatic")
    def automatic_update(body: AutomaticUpdate, x_sociolit_token: str | None = Header(default=None)):
        authorize(x_sociolit_token)
        try:
            return app.state.updater.set_automatic(body.enabled)
        except (UpdateError, OSError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/research/recent")
    def recent_queries(x_sociolit_token: str | None = Header(default=None)):
        authorize(x_sociolit_token)
        return research.recent_searches(store)

    @app.post("/api/research/recent/clear")
    def clear_recent_queries(x_sociolit_token: str | None = Header(default=None)):
        authorize(x_sociolit_token)
        with store.connect() as db:
            db.execute("DELETE FROM recent_searches")
        return {"saved": True}

    @app.get("/api/research/reading")
    def reading_records(status: str = "", favorite: bool = False, archived: bool = False,
                        x_sociolit_token: str | None = Header(default=None)):
        authorize(x_sociolit_token)
        if status not in ("", "to_read", "reading", "done"):
            raise HTTPException(400, "阅读状态无效")
        return research.reading_list(store, status, favorite, archived)

    @app.post("/api/research/reading")
    def mark_reading(body: ReadingSetting, x_sociolit_token: str | None = Header(default=None)):
        authorize(x_sociolit_token)
        try:
            research.mark_reading(store, **body.model_dump())
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"saved": True}

    @app.get("/api/research")
    def research_records(x_sociolit_token: str | None = Header(default=None)):
        authorize(x_sociolit_token)
        return {"searches": research.list_records(store, "searches"), "notes": research.list_records(store, "notes")}

    @app.post("/api/research/searches")
    def save_search(body: SavedSearch, x_sociolit_token: str | None = Header(default=None)):
        authorize(x_sociolit_token)
        if body.query.mode not in ("fulltext", "semantic", "hybrid"):
            raise HTTPException(400, "不支持的检索方式。")
        return {"id": research.save_search(store, body.name, body.query.model_dump())}

    @app.post("/api/research/notes")
    def save_note(body: ReadingNote, x_sociolit_token: str | None = Header(default=None)):
        authorize(x_sociolit_token)
        source = {}
        with store.connect() as db:
            if body.id:
                old = db.execute("SELECT source_json FROM reading_notes WHERE id=?", (body.id,)).fetchone()
                if not old:
                    raise HTTPException(404, "笔记不存在。")
                source = json.loads(old[0])
            elif body.source_chunk_id is not None:
                row = db.execute("""SELECT c.*,i.title FROM chunks c JOIN items i ON i.id=c.item_id
                    WHERE c.id=?""", (body.source_chunk_id,)).fetchone()
                if not row:
                    raise HTTPException(404, "来源片段已变化，请重新检索后保存。")
                if not secrets.compare_digest(body.source_digest, chunk_digest(row)):
                    raise HTTPException(409, "来源片段已变化，请重新检索，避免把笔记关联到错误原文。")
                source = {k: row[k] for k in ("item_id", "file_id", "title", "page", "page_label", "kind", "text")}
                source["chunk_id"] = row["id"]
        return {"id": research.save_note(store, body.title, body.body, source, body.id)}

    @app.post("/api/research/notes/{identity}/archive")
    def archive_note(identity: str, x_sociolit_token: str | None = Header(default=None)):
        authorize(x_sociolit_token)
        with store.connect() as db:
            db.execute("UPDATE reading_notes SET archived=1-archived WHERE id=?", (identity,))
        return {"saved": True}

    @app.post("/api/ocr/languages")
    def ocr_languages(x_sociolit_token: str | None = Header(default=None)):
        authorize(x_sociolit_token)
        try:
            return windows_ocr({"action": "languages"})
        except (RuntimeError, OSError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/subscriptions/{name}/pause")
    def pause_subscription(name: str, x_sociolit_token: str | None = Header(default=None)):
        authorize(x_sociolit_token)
        def pause():
            saved = store.state("journal-feed:" + name)
            if not saved:
                raise ValueError("该期刊尚未配置自定义 RSS。")
            saved["enabled"] = False
            store.set_state("journal-feed:" + name, saved)
            apply_feeds(store, config)
            return {"saved": True}
        return mutate(pause)

    @app.post("/api/subscriptions")
    def subscription(body: FeedSettings, x_sociolit_token: str | None = Header(default=None)):
        authorize(x_sociolit_token)
        return mutate(lambda: configure_feed(store, config, body.name, body.url, body.enabled))

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
    def start_job(action: str, body: OCRSettings | None = None, x_sociolit_token: str | None = Header(default=None)):
        authorize(x_sociolit_token)
        from .scheduler import discover_due
        from .semantic import prepare_model
        body = body or OCRSettings()
        def ocr_run(progress):
            result = process_ocr(store, allowed_roots(config), body.language, max_pages=body.max_pages, progress=progress)
            store.set_state("ocr_summary", result)
            return result
        actions = {
            "ocr": lambda progress: mutate(lambda: ocr_run(progress)),
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
        if body.mode not in ("fulltext", "semantic", "hybrid"):
            raise HTTPException(400, "Unknown search mode")
        research.remember_search(store, body.model_dump())
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
        reading = research.reading_states(store, [row["item_id"] for row in rows])
        for row in rows:
            row["reading"] = reading.get(row["item_id"], {})
            row["source_digest"] = chunk_digest(row)
            row.pop("source", None)
            row["pdf_url"] = "/api/pdf/" + quote(row["file_id"], safe="") + "#page=" + str(row["page"]) if row["file_id"] and row["page"] else None
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
            rows = db.execute("""SELECT i.title,f.status,f.detail,
                (SELECT count(*) FROM ocr_pages op WHERE op.file_id=f.id) AS ocr_pages FROM files f
                JOIN items i ON i.id=f.item_id WHERE f.detail != '' ORDER BY f.status,i.title""").fetchall()
        entries = []
        for row in rows:
            status, detail = row["status"], row["detail"]
            if row["ocr_pages"]:
                message = f"已检查 {row['ocr_pages']} 页 OCR；原 PDF 未修改，可继续处理剩余扫描页。识别文字需核对。"
            elif status == "missing":
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
