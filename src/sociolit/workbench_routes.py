from fastapi import Header, HTTPException
from filelock import FileLock
from pydantic import BaseModel, Field

from . import appearance, graph, research_profiles


class Appearance(BaseModel):
    design: str | None = Field(default=None, max_length=20)
    theme: str = Field(max_length=20)
    motion: str = Field(max_length=20)
    density: str = Field(max_length=20)
    auto_embed: bool


class ResearchProfile(BaseModel):
    identity: str = Field(min_length=1, max_length=30)


class GraphQuery(BaseModel):
    query: str = Field(default='', max_length=200)
    seed: str = Field(default='', max_length=1000)
    limit: int = Field(default=50, ge=10, le=80)
    include_auto: bool = True
    include_archived: bool = False


class Link(BaseModel):
    source: str = Field(min_length=1, max_length=1000)
    target: str = Field(min_length=1, max_length=1000)
    kind: str = Field(max_length=20)
    note: str = Field(default='', max_length=1000)


class GraphExpansion(BaseModel):
    seed: str = Field(min_length=1, max_length=1000)
    known_ids: list[str] = Field(max_length=80)
    limit: int = Field(default=8, ge=1, le=12)
    include_auto: bool = True
    include_archived: bool = False


class ArchiveLink(BaseModel):
    identity: str = Field(min_length=32, max_length=32)
    revision: str = Field(min_length=32, max_length=32)
    archived: bool


def attach_workbench(app, store, authorize, mutate):
    graph.initialize(store)

    def write(function):
        def run():
            if app.state.jobs.snapshot()['state'] == 'running':
                raise ValueError('请等待资料任务完成后再修改关系或设置。')
            with FileLock(str(store.directory / 'library.lock'), timeout=0.1):
                return function()
        return mutate(run)

    @app.get('/api/appearance')
    def appearance_get(x_sociolit_token: str | None = Header(default=None)):
        authorize(x_sociolit_token)
        return appearance.read(store.directory)

    @app.get('/api/research/profile')
    def research_profile_get(x_sociolit_token: str | None = Header(default=None)):
        authorize(x_sociolit_token)
        try:
            return research_profiles.catalog(store.directory)
        except (ValueError, OSError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post('/api/research/profile')
    def research_profile_save(body: ResearchProfile, x_sociolit_token: str | None = Header(default=None)):
        authorize(x_sociolit_token)
        return write(lambda: research_profiles.save(store.directory, body.identity))

    @app.post('/api/appearance')
    def appearance_save(body: Appearance, x_sociolit_token: str | None = Header(default=None)):
        authorize(x_sociolit_token)
        return write(lambda: appearance.save(store.directory, body.model_dump(exclude_none=True)))

    @app.get('/api/literature/catalog')
    def catalog(query: str = '', x_sociolit_token: str | None = Header(default=None)):
        authorize(x_sociolit_token)
        if len(query) > 200:
            raise HTTPException(400, '题名或标签检索最多200字。')
        return graph.catalog(store, query)

    @app.post('/api/graph')
    def graph_get(body: GraphQuery, x_sociolit_token: str | None = Header(default=None)):
        authorize(x_sociolit_token)
        if app.state.jobs.snapshot()['state'] == 'running':
            raise HTTPException(409, '请在资料任务完成后刷新图谱。')
        return mutate(lambda: graph.build(store, **body.model_dump()))

    @app.post('/api/graph/links')
    def link_create(body: Link, x_sociolit_token: str | None = Header(default=None)):
        authorize(x_sociolit_token)
        return write(lambda: graph.create_link(store, body.source, body.target, body.kind, body.note))

    @app.post('/api/graph/expand')
    def graph_expand(body: GraphExpansion, x_sociolit_token: str | None = Header(default=None)):
        authorize(x_sociolit_token)
        if app.state.jobs.snapshot()['state'] == 'running':
            raise HTTPException(409, '请在资料任务完成后展开图谱。')
        return mutate(lambda: graph.expand_neighbors(store, **body.model_dump()))

    @app.post('/api/graph/links/archive')
    def link_archive(body: ArchiveLink, x_sociolit_token: str | None = Header(default=None)):
        authorize(x_sociolit_token)
        return write(lambda: graph.archive(store, body.identity, body.revision, body.archived))

    @app.get('/api/maintenance')
    def maintenance(x_sociolit_token: str | None = Header(default=None)):
        authorize(x_sociolit_token)
        with store.connect() as db:
            files = dict(db.execute('SELECT status,count(*) FROM files GROUP BY status'))
        last = store.state('last_import', {})
        return {'duplicates': graph.duplicates(store), 'files': files,
                'last_import': {key: value for key, value in last.items() if key != 'warnings'},
                'workflow': store.state('workflow_summary', {}), 'appearance': appearance.read(store.directory),
                'message': '软件本地完成增量同步、书目规范化、批注快照和索引更新。重复候选需在 Zotero 核对；私人原文不会由清理步骤删除。'}
