"""User-created research records, independent of Zotero sync deletion."""
import json
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from hashlib import sha256
from html import escape


def initialize(store):
    with store.connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS saved_searches (
          id TEXT PRIMARY KEY, name TEXT NOT NULL, query_json TEXT NOT NULL, updated TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS reading_notes (
          id TEXT PRIMARY KEY, title TEXT NOT NULL, body TEXT NOT NULL, source_json TEXT NOT NULL,
          updated TEXT NOT NULL, archived INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS recent_searches (
          id TEXT PRIMARY KEY, query_json TEXT NOT NULL, updated TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS reading_list (
          item_id TEXT PRIMARY KEY, title TEXT NOT NULL, metadata_json TEXT NOT NULL,
          status TEXT NOT NULL, favorite INTEGER NOT NULL DEFAULT 0,
          archived INTEGER NOT NULL DEFAULT 0, updated TEXT NOT NULL);
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


def remember_search(store, query):
    value = json.dumps(query, ensure_ascii=False, sort_keys=True)
    identity = sha256(value.encode()).hexdigest()
    try:
        with store.connect() as db:
            db.execute("PRAGMA busy_timeout=100")
            db.execute("INSERT OR REPLACE INTO recent_searches VALUES(?,?,?)",
                       (identity, value, datetime.now(timezone.utc).isoformat()))
            db.execute("DELETE FROM recent_searches WHERE id NOT IN (SELECT id FROM recent_searches ORDER BY updated DESC LIMIT 20)")
    except sqlite3.OperationalError as exc:
        if "locked" not in str(exc).lower() and "busy" not in str(exc).lower():
            raise  # Optional history must not block read-only search during indexing.


def recent_searches(store):
    with store.connect() as db:
        return [json.loads(r[0]) for r in db.execute("SELECT query_json FROM recent_searches ORDER BY updated DESC LIMIT 20")]


def mark_reading(store, item_id, status, favorite, archived=False):
    if status not in ("to_read", "reading", "done"):
        raise ValueError("请选择待读、在读或已读。")
    with store.connect() as db:
        item = db.execute("SELECT title,metadata FROM items WHERE id=?", (item_id,)).fetchone()
        previous = db.execute("SELECT * FROM reading_list WHERE item_id=?", (item_id,)).fetchone()
        if not item and not previous:
            raise ValueError("该文献不在当前资料库或阅读清单中。")
        if item:
            metadata = json.loads(item["metadata"])
            title = item["title"]
            details = json.dumps({key: metadata.get(key) for key in ("authors", "year", "journal", "doi")}, ensure_ascii=False)
        else:
            title, details = previous["title"], previous["metadata_json"]
        db.execute("""INSERT INTO reading_list VALUES(?,?,?,?,?,?,?) ON CONFLICT(item_id) DO UPDATE SET
            title=excluded.title,metadata_json=excluded.metadata_json,status=excluded.status,
            favorite=excluded.favorite,archived=excluded.archived,updated=excluded.updated""",
            (item_id, title, details, status, int(favorite), int(archived), datetime.now(timezone.utc).isoformat()))


def reading_list(store, status="", favorite=False, archived=False):
    with store.connect() as db:
        rows = db.execute("""SELECT r.*,i.id IS NOT NULL AS available FROM reading_list r
            LEFT JOIN items i ON i.id=r.item_id WHERE (?='' OR r.status=?)
            AND (?=0 OR r.favorite=1) AND r.archived=? ORDER BY r.updated DESC LIMIT 500""",
            (status, status, int(favorite), int(archived))).fetchall()
    return [dict(item_id=r["item_id"], title=r["title"], metadata=json.loads(r["metadata_json"]),
                 status=r["status"], favorite=bool(r["favorite"]), archived=bool(r["archived"]),
                 available=bool(r["available"])) for r in rows]


def reading_states(store, item_ids):
    ids = list(set(item_ids))
    if not ids:
        return {}
    with store.connect() as db:
        rows = db.execute("SELECT item_id,status,favorite FROM reading_list WHERE archived=0 AND item_id IN ("
                          + ",".join("?" for _ in ids) + ")", ids).fetchall()
    return {r["item_id"]: dict(status=r["status"], favorite=bool(r["favorite"])) for r in rows}


def notes_markdown(store):
    """Export every active note, including source snapshots; never execute note markup."""
    yield "# 阅读笔记\n\n摘录为保存时的来源快照，引用前请核对原文。\n\n"
    def plain(value):
        text = escape(str(value or "").replace("\r", " ").replace("\n", " "))
        return re.sub(r"([\\`*_{}\[\]()#+.!|>\-])", r"\\\1", text)

    def literal(value):
        text = str(value or "")
        fence = "`" * max(3, max((len(run) for run in re.findall(r"`+", text)), default=0) + 1)
        return fence + "text\n" + text + "\n" + fence + "\n\n"
    with store.connect() as db:
        for row in db.execute("SELECT * FROM reading_notes WHERE archived=0 ORDER BY updated DESC"):
            title = plain(row["title"])
            yield "## " + title + "\n\n" + literal(row["body"])
            source = json.loads(row["source_json"])
            if source:
                yield "来源：" + plain(source.get("title") or "未记录题名") + "\n\n"
                if source.get("page"):
                    label = "；文件页标签：" + plain(source["page_label"]) if source.get("page_label") else ""
                    yield "PDF 第 " + str(source["page"]) + " 页" + label + "。\n\n"
                if source.get("kind") == "ocr":
                    yield "OCR 识别摘录，需核对原文。\n\n"
                yield literal(source.get("text", ""))
