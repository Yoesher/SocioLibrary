"""SQLite source of truth. All text, notes and vectors stay in this local database."""
import json
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path


def terms(text: str) -> list[str]:
    result = re.findall(r"[a-z0-9]+", text.lower())
    for run in re.findall(r"[\u3400-\u9fff]+", text):
        result.extend(run)
        result.extend(run[i:i + 2] for i in range(len(run) - 1))
    return result


class Store:
    def __init__(self, directory: str | Path):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "library.sqlite3"
        with self.connect() as db:
            db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS items (
              id TEXT PRIMARY KEY, source TEXT NOT NULL, item_key TEXT NOT NULL,
              title TEXT NOT NULL, kind TEXT NOT NULL, metadata TEXT NOT NULL, fingerprint TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS files (
              id TEXT PRIMARY KEY, item_id TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
              path TEXT NOT NULL, sha256 TEXT NOT NULL, status TEXT NOT NULL, detail TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS chunks (
              id INTEGER PRIMARY KEY, item_id TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
              file_id TEXT REFERENCES files(id) ON DELETE CASCADE,
              page INTEGER, page_label TEXT, ordinal INTEGER NOT NULL,
              kind TEXT NOT NULL, text TEXT NOT NULL);
            CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(tokens);
            CREATE TRIGGER IF NOT EXISTS chunks_delete AFTER DELETE ON chunks BEGIN
              DELETE FROM chunks_fts WHERE rowid=old.id;
            END;
            CREATE TABLE IF NOT EXISTS vectors (
              chunk_id INTEGER NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
              model TEXT NOT NULL, embedding TEXT NOT NULL, PRIMARY KEY(chunk_id,model));
            CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS chunks_item_idx ON chunks(item_id);
            CREATE INDEX IF NOT EXISTS files_item_idx ON files(item_id);
            CREATE INDEX IF NOT EXISTS vectors_model_idx ON vectors(model,chunk_id);
            PRAGMA user_version=1;
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def add_chunk(self, db, *, item_id, text, kind, ordinal=0, file_id=None, page=None, page_label=None):
        if not text.strip():
            return
        cursor = db.execute(
            "INSERT INTO chunks(item_id,file_id,page,page_label,ordinal,kind,text) VALUES(?,?,?,?,?,?,?)",
            (item_id, file_id, page, page_label, ordinal, kind, text))
        db.execute("INSERT INTO chunks_fts(rowid,tokens) VALUES(?,?)", (cursor.lastrowid, " ".join(terms(text))))
        return cursor.lastrowid

    def state(self, key, default=None):
        with self.connect() as db:
            row = db.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set_state(self, key, value):
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO state VALUES(?,?)", (key, json.dumps(value, ensure_ascii=False)))

    def stats(self):
        with self.connect() as db:
            return {name: db.execute(f"SELECT count(*) FROM {name}").fetchone()[0]
                    for name in ("items", "files", "chunks", "vectors")}

    def search(self, query: str, limit: int = 20, *, item_ids=None):
        tokens = list(dict.fromkeys(terms(query)))[:64]
        if not tokens:
            return []
        expression = " AND ".join('"' + t + '"' for t in tokens)
        with self.connect() as db:
            scope = ""
            if item_ids is not None:
                db.execute("CREATE TEMP TABLE search_items(id TEXT PRIMARY KEY)")
                db.executemany("INSERT INTO search_items VALUES(?)", [(item,) for item in item_ids])
                scope = " AND c.item_id IN (SELECT id FROM search_items) "
            rows = db.execute("""
              SELECT c.*,i.title,i.item_key,i.source,bm25(chunks_fts) AS score
              FROM chunks_fts JOIN chunks c ON c.id=chunks_fts.rowid JOIN items i ON i.id=c.item_id
              WHERE chunks_fts MATCH ? """ + scope + " ORDER BY score LIMIT ?", (expression, min(max(limit, 1), 100))).fetchall()
        return [dict(row) for row in rows]
