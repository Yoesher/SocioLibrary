"""Small status snapshots invalidated by commits on the same SQLite connection.

Only display statistics are cached. Searches, write permissions, task progress,
and update/install decisions always use live state.
"""
import copy
import sqlite3
import threading
import time
import weakref
from hashlib import sha256
from pathlib import Path

from . import catalog_semantic


class LibraryStatus:
    def __init__(self, store, ttl=30, clock=time.monotonic):
        self.store, self.ttl, self.clock = store, ttl, clock
        self._lock = threading.Lock()
        self._observer = self._finalize = None
        self._identity = self._key = self._value = None
        self._time = 0

    def close(self):
        with self._lock:
            self._disconnect()

    def _disconnect(self):
        if self._finalize:
            self._finalize()
        self._observer = self._finalize = None
        self._key = self._value = None

    def get(self, scope_label, model_path):
        manifest = Path(model_path) / 'sociolit-model.json'
        model = sha256(manifest.read_bytes()).hexdigest() if manifest.is_file() else None
        with self._lock:
            stat = self.store.path.stat()
            identity = (stat.st_dev, stat.st_ino)
            if self._observer is None or identity != self._identity:
                self._disconnect()
                self._observer = sqlite3.connect(self.store.path.resolve().as_uri() + '?mode=ro',
                                                 uri=True, check_same_thread=False, timeout=1)
                self._finalize = weakref.finalize(self, self._observer.close)
                self._identity = identity
            revision = self._observer.execute('PRAGMA data_version').fetchone()[0]
            key = (revision, scope_label, model)
            now = self.clock()
            if key != self._key or self._value is None or now - self._time >= self.ttl:
                value = self._read(scope_label, model)
                # A concurrent importer may have committed between our queries.
                # Return the fresh display data, but do not cache mixed revisions.
                if self._observer.execute('PRAGMA data_version').fetchone()[0] == revision:
                    self._key, self._value, self._time = key, copy.deepcopy(value), now
                else:
                    self._key = self._value = None
                return value
            return copy.deepcopy(self._value)

    def _read(self, scope_label, model):
        with self.store.connect() as db:
            problems = [dict(r) for r in db.execute('''SELECT i.title,f.status,f.detail,
                (SELECT count(*) FROM ocr_pages op WHERE op.file_id=f.id) AS ocr_pages FROM files f
                JOIN items i ON i.id=f.item_id WHERE f.detail != '' LIMIT 10''')]
            count = db.execute("SELECT count(*) FROM files WHERE detail != ''").fetchone()[0]
        last_import = self.store.state('last_import')
        if isinstance(last_import, dict):
            last_import = {k: v for k, v in last_import.items() if k != 'warnings'}
        scope = self.store.state('semantic_scope')
        progress = None
        catalog = catalog_semantic.status(self.store, model) if model else {'done': 0, 'total': 0, 'ready': False}
        if model and isinstance(scope, dict) and scope.get('label') == scope_label and scope.get('item_ids'):
            with self.store.connect() as db:
                db.execute('CREATE TEMP TABLE scope_items(id TEXT PRIMARY KEY)')
                db.executemany('INSERT INTO scope_items VALUES(?)', [(item,) for item in scope['item_ids']])
                total = db.execute('SELECT count(*) FROM chunks c JOIN scope_items s ON s.id=c.item_id').fetchone()[0]
                done = db.execute('''SELECT count(*) FROM vectors v JOIN chunks c ON c.id=v.chunk_id
                    JOIN scope_items s ON s.id=c.item_id WHERE v.model=?''', (model,)).fetchone()[0]
                progress = {'done': done, 'total': total}
        return {'stats': self.store.stats(), 'file_notices': problems, 'file_notice_count': count,
                'last_import': last_import, 'semantic_progress': progress, 'catalog_progress': catalog,
                'import_incomplete': self.store.state('import_incomplete', False),
                'discovery': self.store.state('last_discovery'),
                'ocr_pages': self.store.state('ocr_summary', {}).get('pages', 0)}
