"""Read-only annotation snapshots, independent of later Zotero deletion."""
import json
import re
from datetime import datetime, timezone
from hashlib import sha256
from urllib.parse import quote


def normalize(data, key, attachments):
    parent = str(data.get("parentItem") or "")
    attachment = attachments.get(parent)
    if not attachment:
        return None
    position = data.get("annotationPosition", {})
    try:
        if isinstance(position, str):
            position = json.loads(position) if len(position) < 300000 else {}
    except ValueError:
        position = {}
    page = position.get("pageIndex") if isinstance(position, dict) else None
    page = page + 1 if type(page) is int and 0 <= page < 3000 else None
    from .indexing import plain
    tags = [str(tag.get("tag", "") if isinstance(tag, dict) else tag)[:200]
            for tag in (data.get("tags") or [])[:100]]
    color = str(data.get("annotationColor") or "")
    return {"key": key, "parent_key": str(attachment.get("parentItem") or parent), "attachment_key": parent,
            "type": str(data.get("annotationType") or "unknown")[:40],
            "text": str(data.get("annotationText") or "")[:20000],
            "comment": plain(str(data.get("annotationComment") or ""))[:20000],
            "page": page, "page_label": str(data.get("annotationPageLabel") or "")[:100],
            "color": color if re.fullmatch(r"#[0-9a-fA-F]{6}", color) else "", "tags": tags,
            "truncated": len(str(data.get("annotationText") or "")) > 20000
                         or len(str(data.get("annotationComment") or "")) > 20000 or len(data.get("tags") or []) > 100}


def initialize(store):
    with store.connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS zotero_annotations (
          id TEXT PRIMARY KEY, source TEXT NOT NULL, item_id TEXT NOT NULL, file_id TEXT NOT NULL,
          data_json TEXT NOT NULL, citation_json TEXT NOT NULL, fingerprint TEXT NOT NULL,
          current INTEGER NOT NULL DEFAULT 1, updated TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS annotations_source_idx ON zotero_annotations(source,current);
        CREATE TABLE IF NOT EXISTS annotation_chunks (
          annotation_id TEXT NOT NULL, chunk_id INTEGER NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
          PRIMARY KEY(annotation_id,chunk_id));
        """)


def sync_snapshots(store, snapshot):
    if snapshot.annotations is None:
        return {"returned": None, "changed": 0}
    initialize(store)
    source = snapshot.source_id
    stamp = datetime.now(timezone.utc).isoformat()
    changed = 0
    from .indexing import split_text
    with store.connect() as db:
        db.execute("CREATE TEMP TABLE incoming_annotations(id TEXT PRIMARY KEY)")
        for annotation in snapshot.annotations:
            identity, item_id = source + ":" + annotation["key"], source + ":" + annotation["parent_key"]
            file_id = source + ":" + annotation["attachment_key"]
            item = db.execute("SELECT title,metadata FROM items WHERE id=?", (item_id,)).fetchone()
            if not item:
                continue
            file = db.execute("SELECT sha256,path,status FROM files WHERE id=? AND item_id=?", (file_id, item_id)).fetchone()
            linked_file = bool(file and file[0] and file[1] and file[2] in ("indexed", "needs_ocr"))
            metadata = json.loads(item["metadata"])
            citation = {"title": item["title"], "authors": metadata.get("authors", []), "year": metadata.get("year"),
                        "file_sha256": file[0] if file else "", "file_linked": linked_file}
            raw = json.dumps(annotation, ensure_ascii=False, sort_keys=True)
            citation_raw = json.dumps(citation, ensure_ascii=False, sort_keys=True)
            fingerprint = sha256((raw + citation_raw).encode()).hexdigest()
            old = db.execute("SELECT fingerprint FROM zotero_annotations WHERE id=?", (identity,)).fetchone()
            linked = db.execute("SELECT count(*) FROM annotation_chunks WHERE annotation_id=?", (identity,)).fetchone()[0]
            db.execute("INSERT INTO incoming_annotations VALUES(?)", (identity,))
            if old and old[0] == fingerprint and (linked or not (annotation["text"] or annotation["comment"])):
                db.execute("UPDATE zotero_annotations SET current=1 WHERE id=?", (identity,))
                continue
            _remove_index(db, identity)
            db.execute("""INSERT INTO zotero_annotations VALUES(?,?,?,?,?,?,?,1,?) ON CONFLICT(id) DO UPDATE SET
                item_id=excluded.item_id,file_id=excluded.file_id,data_json=excluded.data_json,
                citation_json=excluded.citation_json,fingerprint=excluded.fingerprint,current=1,updated=excluded.updated""",
                (identity, source, item_id, file_id, raw, citation_raw, fingerprint, stamp))
            ordinal = 0
            for label, text in (("【Zotero 摘录】", annotation["text"]),
                                ("【个人批注，不是作者原文】", annotation["comment"])):
                for block in split_text(text):
                    chunk = store.add_chunk(db, item_id=item_id, file_id=file_id if linked_file else None,
                        page=annotation["page"], page_label=annotation["page_label"],
                        text=label + "\n" + block, kind="annotation", ordinal=ordinal)
                    db.execute("INSERT INTO annotation_chunks VALUES(?,?)", (identity, chunk))
                    ordinal += 1
            changed += 1
        missing = db.execute("""SELECT id FROM zotero_annotations WHERE source=? AND current=1
            AND id NOT IN (SELECT id FROM incoming_annotations)""", (source,)).fetchall()
        for row in missing:
            _remove_index(db, row[0])
        db.execute("""UPDATE zotero_annotations SET current=0 WHERE source=?
            AND id NOT IN (SELECT id FROM incoming_annotations)""", (source,))
    return {"returned": len(snapshot.annotations), "changed": changed}


def _remove_index(db, identity):
    db.execute("DELETE FROM chunks WHERE id IN (SELECT chunk_id FROM annotation_chunks WHERE annotation_id=?)", (identity,))


def records(store, query="", *, include_missing=False, offset=0, limit=50):
    query = query.strip()[:200]
    with store.connect() as db:
        where = """WHERE (?=1 OR a.current=1) AND (?='' OR instr(lower(a.data_json || a.citation_json),lower(?))>0)"""
        params = (int(include_missing), query, query)
        total = db.execute("SELECT count(*) FROM zotero_annotations a " + where, params).fetchone()[0]
        rows = db.execute("SELECT a.* FROM zotero_annotations a " + where + " ORDER BY a.updated DESC,a.id LIMIT ? OFFSET ?",
                          (*params, limit, offset)).fetchall()
        output = []
        for row in rows:
            data, citation = json.loads(row["data_json"]), json.loads(row["citation_json"])
            file = db.execute("SELECT sha256,path,status FROM files WHERE id=?", (row["file_id"],)).fetchone()
            available = bool(row["current"] and file and file[0] and file[1]
                             and file[2] in ("indexed", "needs_ocr") and file[0] == citation.get("file_sha256"))
            item = {"id": row["id"], "revision": row["fingerprint"], "item_id": row["item_id"],
                    "current": bool(row["current"]), "citation": {k: citation.get(k) for k in ("title", "authors", "year")},
                    **{k: data[k] for k in ("type", "text", "comment", "page", "page_label", "color", "tags")},
                    "truncated": data.get("truncated", False)}
            item["pdf_url"] = ("/api/pdf/" + quote(row["file_id"], safe="") + "#page=" + str(data["page"])) \
                if available and data["page"] else None
            output.append(item)
    return {"records": output, "total": total, "offset": offset, "limit": limit}


def note_snapshot(store, identity, revision):
    with store.connect() as db:
        row = db.execute("SELECT * FROM zotero_annotations WHERE id=?", (identity,)).fetchone()
    if not row or row["fingerprint"] != revision:
        raise ValueError("批注已变化，请刷新后再保存。")
    data, citation = json.loads(row["data_json"]), json.loads(row["citation_json"])
    page = f"PDF 第 {data['page']} 页" if data["page"] else "未提供有效 PDF 页序"
    body = "Zotero 批注快照 · " + page + "\n\n摘录：\n" + (data["text"] or "（无文字摘录）")
    body += "\n\n个人批注：\n" + (data["comment"] or "（无评论）")
    if len(body) > 20000:
        raise ValueError("批注较长，已保留在批注列表；请分段整理到阅读笔记，不会静默截短笔记。")
    source = {"title": citation["title"], "page": data["page"], "page_label": data["page_label"],
              "kind": "annotation", "text": data["text"], "annotation_id": identity}
    return citation["title"][:250] + " · Zotero 批注", body, source
