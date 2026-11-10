from fastapi import Header, HTTPException
from filelock import FileLock, Timeout
from pydantic import BaseModel, Field

from . import annotations, comparisons, literature, research
from .ai_routes import AIConfirm, Source
from .comparison_ai import ComparisonAI
from .scope import active_scope


class ItemRequest(BaseModel):
    item_id: str = Field(min_length=1, max_length=1000)
    mode: str = Field(default="metadata", max_length=20)
    query: str = Field(default="", max_length=500)


class AnnotationNote(BaseModel):
    identity: str = Field(min_length=1, max_length=1000)
    revision: str = Field(min_length=64, max_length=64)


class NewComparison(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    sources: list[Source] = Field(min_length=2, max_length=8)


class Cell(BaseModel):
    text: str = Field(max_length=2000)
    citations: list[str] = Field(max_length=8)
    reviewed: bool = False


class ComparisonSave(BaseModel):
    identity: str = Field(min_length=32, max_length=32)
    revision: str = Field(min_length=32, max_length=32)
    title: str = Field(min_length=1, max_length=120)
    cells: dict[str, dict[str, Cell]]


class ComparisonArchive(BaseModel):
    identity: str = Field(min_length=32, max_length=32)
    revision: str = Field(min_length=32, max_length=32)
    archived: bool


class ComparisonPreview(BaseModel):
    identity: str = Field(min_length=32, max_length=32)
    profile_id: str = Field(min_length=32, max_length=32)
    question: str = Field(default="", max_length=1000)


class DraftAdopt(BaseModel):
    identity: str = Field(min_length=1, max_length=100)


def attach_literature(app, store, config, authorize, mutate, embedder):
    annotations.initialize(store)
    comparisons.initialize(store)
    ai = ComparisonAI(store, app.state.ai)
    app.state.comparison_ai = ai

    def guarded(function):
        def run():
            if app.state.maintenance.is_set() or app.state.jobs.snapshot()["state"] == "running":
                raise ValueError("请先等待资料任务或升级完成。")
            try:
                with FileLock(str(store.directory / "library.lock"), timeout=0.1):
                    return function()
            except Timeout as exc:
                raise ValueError("资料库正被其他任务使用，请稍后重试。") from exc
        return mutate(run)

    @app.post("/api/literature/recommend")
    def recommend(body: ItemRequest, x_sociolit_token: str | None = Header(default=None)):
        authorize(x_sociolit_token)

        def run():
            if body.mode == "metadata":
                return literature.recommend_metadata(store, body.item_id)
            if body.mode != "semantic":
                raise ValueError("推荐方式无效。")
            scope = active_scope(store, config)
            return literature.recommend_semantic(store, body.item_id, embedder(),
                item_ids=scope["item_ids"] if scope else None, scope=scope["label"] if scope else "全部语义索引")
        return guarded(run)

    @app.post("/api/literature/excerpts")
    def excerpts(body: ItemRequest, x_sociolit_token: str | None = Header(default=None)):
        authorize(x_sociolit_token)
        return guarded(lambda: literature.excerpts(store, body.item_id, body.query))

    @app.get("/api/annotations")
    def annotation_records(query: str = "", include_missing: bool = False, offset: int = 0,
                           x_sociolit_token: str | None = Header(default=None)):
        authorize(x_sociolit_token)
        if len(query) > 200 or not 0 <= offset <= 10000000:
            raise HTTPException(400, "批注筛选条件无效。")
        return annotations.records(store, query, include_missing=include_missing, offset=offset)

    @app.post("/api/annotations/note")
    def annotation_note(body: AnnotationNote, x_sociolit_token: str | None = Header(default=None)):
        authorize(x_sociolit_token)

        def run():
            title, text, source = annotations.note_snapshot(store, body.identity, body.revision)
            return {"id": research.save_note(store, title, text, source)}
        return guarded(run)

    @app.get("/api/comparisons")
    def list_comparisons(include_archived: bool = False, x_sociolit_token: str | None = Header(default=None)):
        authorize(x_sociolit_token)
        return comparisons.list_boards(store, include_archived)

    @app.get("/api/comparisons/{identity}")
    def get_comparison(identity: str, x_sociolit_token: str | None = Header(default=None)):
        authorize(x_sociolit_token)
        try:
            return comparisons.get(store, identity)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.post("/api/comparisons")
    def create_comparison(body: NewComparison, x_sociolit_token: str | None = Header(default=None)):
        authorize(x_sociolit_token)
        return guarded(lambda: comparisons.create(store, body.title, [source.model_dump() for source in body.sources]))

    @app.post("/api/comparisons/save")
    def save_comparison(body: ComparisonSave, x_sociolit_token: str | None = Header(default=None)):
        authorize(x_sociolit_token)
        cells = {paper: {key: cell.model_dump() for key, cell in fields.items()} for paper, fields in body.cells.items()}
        return guarded(lambda: comparisons.save(store, body.identity, body.revision, body.title, cells))

    @app.post("/api/comparisons/archive")
    def archive_comparison(body: ComparisonArchive, x_sociolit_token: str | None = Header(default=None)):
        authorize(x_sociolit_token)
        return guarded(lambda: comparisons.archive(store, body.identity, body.revision, body.archived))

    @app.post("/api/ai/comparison/preview")
    def preview_comparison(body: ComparisonPreview, x_sociolit_token: str | None = Header(default=None)):
        authorize(x_sociolit_token)
        return guarded(lambda: ai.prepare(body.identity, body.profile_id, body.question))

    @app.post("/api/ai/comparison/ask")
    def ask_comparison(body: AIConfirm, x_sociolit_token: str | None = Header(default=None)):
        authorize(x_sociolit_token)
        if not body.consent:
            raise HTTPException(400, "请先核对并确认本次发送范围和可能费用。")
        return guarded(lambda: ai.ask(body.confirmation))

    @app.post("/api/ai/comparison/adopt")
    def adopt_comparison(body: DraftAdopt, x_sociolit_token: str | None = Header(default=None)):
        authorize(x_sociolit_token)
        return guarded(lambda: ai.adopt(body.identity))
