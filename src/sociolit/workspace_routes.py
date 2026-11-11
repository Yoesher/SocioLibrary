"""Local graph notebooks, metadata inbox and explicit portable exports."""
from fastapi import Header
from fastapi.responses import Response
from filelock import FileLock
from pydantic import BaseModel, Field

from . import graph_views, journal_inbox


class ViewSave(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    state: dict


class ViewArchive(BaseModel):
    revision: str = Field(min_length=32, max_length=32)
    archived: bool


class ViewExport(BaseModel):
    include_annotations: bool = False


class InboxMark(BaseModel):
    item_id: str = Field(min_length=1, max_length=1000)
    read: bool | None = None
    favorite: bool | None = None


def attach_workspace(app, store, authorize, mutate):
    graph_views.initialize(store)
    journal_inbox.sync(store)

    def guarded(action):
        def run():
            if app.state.jobs.snapshot()['state'] == 'running':
                raise ValueError('请等待资料任务完成后再保存研究进度。')
            with FileLock(str(store.directory / 'library.lock'), timeout=.1):
                return action()
        return mutate(run)

    @app.get('/api/graph/views')
    def views(archived: bool = False, x_sociolit_token: str | None = Header(default=None)):
        authorize(x_sociolit_token)
        return graph_views.listing(store, archived)

    @app.post('/api/graph/views')
    def save(body: ViewSave, x_sociolit_token: str | None = Header(default=None)):
        authorize(x_sociolit_token)
        return guarded(lambda: graph_views.save(store, body.name, body.state))

    @app.get('/api/graph/views/{identity}')
    def view(identity: str, x_sociolit_token: str | None = Header(default=None)):
        authorize(x_sociolit_token)
        return mutate(lambda: graph_views.get(store, identity))

    @app.post('/api/graph/views/{identity}/archive')
    def archive(identity: str, body: ViewArchive, x_sociolit_token: str | None = Header(default=None)):
        authorize(x_sociolit_token)
        return guarded(lambda: graph_views.archive(store, identity, body.revision, body.archived))

    @app.post('/api/graph/views/{identity}/export')
    def export(identity: str, body: ViewExport, x_sociolit_token: str | None = Header(default=None)):
        authorize(x_sociolit_token)
        content = guarded(lambda: graph_views.export(store, identity, body.include_annotations))
        return Response(content, media_type='application/zip',
                        headers={'Content-Disposition': 'attachment; filename="SocioLibrary-research.zip"'})

    @app.get('/api/journals/inbox')
    def inbox(query: str = '', journal: str = '', state: str = 'unread', offset: int = 0, limit: int = 20,
              x_sociolit_token: str | None = Header(default=None)):
        authorize(x_sociolit_token)
        return mutate(lambda: journal_inbox.listing(store, query, journal, state, offset, limit))

    @app.post('/api/journals/inbox/mark')
    def mark(body: InboxMark, x_sociolit_token: str | None = Header(default=None)):
        authorize(x_sociolit_token)
        return guarded(lambda: journal_inbox.mark(store, body.item_id, body.read, body.favorite))
