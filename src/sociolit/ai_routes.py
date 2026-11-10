"""Authenticated loopback routes; previewing and saving never call a provider."""
from fastapi import Header, HTTPException
from filelock import FileLock, Timeout
from pydantic import BaseModel, Field

from . import research
from .ai import AIError, Profiles, call_ai
from .ai_context import AIWorkspace


class AIProfile(BaseModel):
    identity: str | None = Field(default=None, max_length=32)
    name: str = Field(min_length=1, max_length=80)
    protocol: str = Field(max_length=20)
    base_url: str = Field(min_length=1, max_length=1000)
    model: str = Field(min_length=1, max_length=150)
    max_output_tokens: int = Field(default=2048, ge=256, le=8192)
    api_key: str | None = Field(default=None, max_length=4096)
    clear_key: bool = False
    token_parameter: str = Field(default="auto", max_length=30)
    disable_thinking: bool = False


class Identity(BaseModel):
    identity: str = Field(min_length=1, max_length=64)


class AITest(Identity):
    confirm_cost: bool = False


class Source(BaseModel):
    chunk_id: int
    digest: str = Field(min_length=64, max_length=64)


class AIPreview(Identity):
    question: str = Field(min_length=1, max_length=2000)
    task: str = Field(default="ask", max_length=20)
    sources: list[Source] = Field(min_length=1, max_length=8)


class AIConfirm(BaseModel):
    confirmation: str = Field(min_length=1, max_length=100)
    consent: bool = False


def attach_ai(app, store, authorize, mutate, *, workspace=None):
    workspace = workspace or AIWorkspace(store, Profiles(store.directory))
    app.state.ai = workspace

    def guarded(function):
        def run():
            if app.state.maintenance.is_set() or app.state.jobs.snapshot()["state"] == "running":
                raise AIError("请等待当前资料任务或升级完成，再使用 AI。")
            try:
                with FileLock(str(store.directory / "library.lock"), timeout=0.1):
                    return function()
            except Timeout as exc:
                raise AIError("资料库正被其他任务使用，请稍后再试。") from exc
        return mutate(run)

    @app.get("/api/ai/profiles")
    def profiles(x_sociolit_token: str | None = Header(default=None)):
        authorize(x_sociolit_token)
        try:
            return workspace.profiles.list()
        except AIError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/ai/profiles")
    def save(body: AIProfile, x_sociolit_token: str | None = Header(default=None)):
        authorize(x_sociolit_token)
        return guarded(lambda: workspace.profiles.save(**body.model_dump()))

    @app.post("/api/ai/delete")
    def delete(body: Identity, x_sociolit_token: str | None = Header(default=None)):
        authorize(x_sociolit_token)
        return guarded(lambda: workspace.profiles.delete(body.identity))

    @app.post("/api/ai/test")
    def test(body: AITest, x_sociolit_token: str | None = Header(default=None)):
        authorize(x_sociolit_token)
        if not body.confirm_cost:
            raise HTTPException(400, "测试会发送固定短提示并可能计费，请先勾选确认；不会发送文献。")

        def run():
            profile = workspace.profiles.get(body.identity)
            result = call_ai(profile, workspace.profiles.key(profile), "Reply briefly.", "Reply OK only.",
                             test=True, factory=workspace.factory)
            return {"connected": True, "usage": result["usage"], "warning": result["warning"]}
        return guarded(run)

    @app.post("/api/ai/preview")
    def preview(body: AIPreview, x_sociolit_token: str | None = Header(default=None)):
        authorize(x_sociolit_token)
        return guarded(lambda: workspace.prepare(body.identity, body.question, body.task,
                                                 [source.model_dump() for source in body.sources]))

    @app.post("/api/ai/ask")
    def ask(body: AIConfirm, x_sociolit_token: str | None = Header(default=None)):
        authorize(x_sociolit_token)
        if not body.consent:
            raise HTTPException(400, "请确认本次发送范围和可能的 API 费用。")
        return guarded(lambda: workspace.ask(body.confirmation))

    @app.post("/api/ai/save-draft")
    def save_draft(body: Identity, x_sociolit_token: str | None = Header(default=None)):
        authorize(x_sociolit_token)

        def run():
            title, text = workspace.draft(body.identity)
            return {"id": research.save_note(store, title, text, {"ai_generated": True})}
        return guarded(run)
