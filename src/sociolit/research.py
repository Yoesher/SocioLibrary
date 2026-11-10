"""User-created research records, independent of Zotero sync deletion."""
import json
import uuid
from datetime import datetime, timezone


def initialize(store):
    with store.connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS saved_searches (
          id TEXT PRIMARY KEY, name TEXT NOT NULL, query_json TEXT NOT NULL, updated TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS reading_notes (
          id TEXT PRIMARY KEY, title TEXT NOT NULL, body TEXT NOT NULL, source_json TEXT NOT NULL,
          updated TEXT NOT NULL, archived INTEGER NOT NULL DEFAULT 0);
        """)


def save_search(store, name, query):
    stamp = datetime.now(timezone.utc).isoformat()
    with store.connect() as db:
        identity = uuid.uuid4().hex
        db.execute("INSERT INTO saved_searches VALUES(?,?,?,?)", (identity, name, json.dumps(query, ensure_ascii=False), stamp))
    return identity


def save_note(store, title, body, source, identity=None):
    stamp = datetime.now(timezone.utc).isoformat()
    identity = identity or uuid.uuid4().hex
    with store.connect() as db:
        db.execute("""INSERT INTO reading_notes VALUES(?,?,?,?,?,0) ON CONFLICT(id) DO UPDATE SET
            title=excluded.title,body=excluded.body,source_json=excluded.source_json,updated=excluded.updated""",
            (identity, title, body, json.dumps(source, ensure_ascii=False), stamp))
    return identity


def list_records(store, kind):
    with store.connect() as db:
        if kind == "searches":
            return [dict(id=r["id"], name=r["name"], query=json.loads(r["query_json"]), updated=r["updated"])
                    for r in db.execute("SELECT * FROM saved_searches ORDER BY updated DESC LIMIT 500")]
        return [dict(id=r["id"], title=r["title"], body=r["body"], source=json.loads(r["source_json"]),
                     updated=r["updated"], archived=bool(r["archived"]))
                for r in db.execute("SELECT * FROM reading_notes ORDER BY updated DESC LIMIT 500")]
