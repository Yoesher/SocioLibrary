import json
from contextlib import nullcontext
from hashlib import sha256
from html.parser import HTMLParser
from pathlib import Path

import pypdfium2 as pdfium
from filelock import FileLock
from pypdf import PdfReader


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def plain(text):
    parser = PlainText()
    parser.feed(text or "")
    return " ".join(parser.parts)


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def file_digest(path):
    result = sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def split_text(text, size=400, overlap=80):
    # Never spans PDF pages: physical page remains an exact locator.
    for start in range(0, len(text), size - overlap):
        block = text[start:start + size].strip()
        if block:
            yield block
        if start + size >= len(text):
            break


def extract_pdf(path):
    if Path(path).stat().st_size > 100 * 1024 * 1024:
        raise ValueError("PDF exceeds the 100 MiB MVP limit")
    doc = pdfium.PdfDocument(path)
    try:
        if len(doc) > 3000:
            raise ValueError("PDF exceeds the 3000-page MVP limit")
        pages = []
        for index in range(len(doc)):
            page = doc[index]
            try:
                textpage = page.get_textpage()
                try:
                    if textpage.count_chars() > 2_000_000:
                        raise ValueError("PDF page text exceeds extraction limit")
                    text = textpage.get_text_bounded().replace("\r\n", "\n")
                    pages.append((index + 1, doc.get_page_label(index) or str(index + 1), text))
                finally:
                    textpage.close()
            finally:
                page.close()
        return pages
    finally:
        doc.close()


def extract_pdf_pypdf(path):
    """Reference extractor retained for controlled comparisons and diagnostics."""
    reader = PdfReader(path)
    if reader.is_encrypted:
        raise ValueError("Encrypted PDF: use a lawfully unlocked local copy")
    if len(reader.pages) > 3000:
        raise ValueError("PDF exceeds the 3000-page MVP limit")
    labels = reader.page_labels
    pages = []
    for number, page in enumerate(reader.pages, 1):
        content = page.get_contents()
        if content and len(content.get_data()) > 20 * 1024 * 1024:
            raise ValueError("PDF page content exceeds extraction limit")
        pages.append((number, labels[number - 1], page.extract_text() or ""))
    return pages


def import_snapshot(store, snapshot, progress=None, *, assume_locked=False):
    if not snapshot.complete:
        raise ValueError("Incomplete Zotero snapshot; existing library was not modified")
    stats = {"items_changed": 0, "files_indexed": 0, "files_unchanged": 0, "removed": 0,
             "warnings": list(snapshot.warnings)}
    source = snapshot.source_id
    progress = progress or (lambda phase, done, total: None)
    is_private = not source.startswith("journals:")
    lock = nullcontext() if assume_locked else FileLock(str(store.directory / "library.lock"), timeout=1)
    with lock:
        if is_private:
            store.set_state("import_incomplete", True)
        # Commit complete metadata as one transaction. PDFs then commit one by
        # one, so a long import can resume without discarding completed work.
        with store.connect() as db:
            present = set()
            for position, item in enumerate(snapshot.items, 1):
                item_id = source + ":" + item["key"]
                present.add(item_id)
                fingerprint = digest(item)
                old = db.execute("SELECT fingerprint FROM items WHERE id=?", (item_id,)).fetchone()
                if old and old[0] == fingerprint:
                    continue
                kind = item.get("item_type", "bibliography")
                db.execute("""INSERT INTO items VALUES(?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                    title=excluded.title,kind=excluded.kind,metadata=excluded.metadata,fingerprint=excluded.fingerprint""",
                    (item_id, source, item["key"], item.get("title") or "Untitled", kind,
                     json.dumps(item, ensure_ascii=False), fingerprint))
                db.execute("DELETE FROM chunks WHERE item_id=? AND file_id IS NULL", (item_id,))
                text = "\n".join([item.get("title", ""), "; ".join(item.get("authors", [])),
                                  item.get("abstract", ""), " ".join(item.get("tags", []))])
                if kind == "note":
                    text = plain(item.get("raw", {}).get("note", item.get("note", "")))
                for ordinal, chunk in enumerate(split_text(plain(text))):
                    store.add_chunk(db, item_id=item_id, text=chunk, kind="note" if kind == "note" else "metadata", ordinal=ordinal)
                stats["items_changed"] += 1
                progress("metadata_index", position, len(snapshot.items))
            # Only a complete identified snapshot can remove stale metadata.
            for old in db.execute("SELECT id FROM items WHERE source=?", (source,)).fetchall():
                if old[0] not in present:
                    db.execute("DELETE FROM items WHERE id=?", (old[0],))
                    stats["removed"] += 1
        attachment_ids = set()
        for position, attachment in enumerate(snapshot.attachments, 1):
            item_id = source + ":" + attachment.parent_key
            if item_id not in present:
                continue
            file_id = source + ":" + attachment.key
            attachment_ids.add(file_id)
            with store.connect() as db:
                old = db.execute("SELECT * FROM files WHERE id=?", (file_id,)).fetchone()
            path = attachment.path
            checksum, status, detail, pages = "", "missing", attachment.warning or "", []
            if path:
                try:
                    checksum = "pdfium-v1:" + file_digest(path)
                    if old and old["sha256"] == checksum and old["status"] in ("indexed", "needs_ocr"):
                        with store.connect() as db:
                            db.execute("UPDATE files SET path=?,item_id=? WHERE id=?", (str(path), item_id, file_id))
                            db.execute("UPDATE chunks SET item_id=? WHERE file_id=?", (item_id, file_id))
                        stats["files_unchanged"] += 1
                        progress("pdf_index", position, len(snapshot.attachments))
                        continue
                    pages = extract_pdf(path)
                    status = "indexed" if any(p[2].strip() for p in pages) else "needs_ocr"
                    empty = [p[0] for p in pages if not p[2].strip()]
                    detail = ("No extractable text on PDF pages: " + ",".join(map(str, empty))) if empty else ""
                except Exception as exc:
                    status, detail = "error", f"{type(exc).__name__}: PDF extraction failed; inspect local file"
            # Replacing a changed/unavailable PDF removes stale text and embeddings.
            with store.connect() as db:
                db.execute("DELETE FROM files WHERE id=?", (file_id,))
                db.execute("INSERT INTO files VALUES(?,?,?,?,?,?)", (file_id, item_id, str(path or ""), checksum, status, detail))
                for page, label, text in pages:
                    for ordinal, chunk in enumerate(split_text(text)):
                        store.add_chunk(db, item_id=item_id, file_id=file_id, page=page, page_label=label,
                                        text=chunk, ordinal=ordinal, kind="pdf")
            if status == "indexed":
                stats["files_indexed"] += 1
            if detail:
                stats["warnings"].append(f"{attachment.key}: {detail}")
            progress("pdf_index", position, len(snapshot.attachments))
        # Unseen attachments are pruned only after every PDF was considered.
        with store.connect() as db:
            rows = db.execute("SELECT f.id FROM files f JOIN items i ON i.id=f.item_id WHERE i.source=?", (source,)).fetchall()
            for row in rows:
                if row[0] not in attachment_ids:
                    db.execute("DELETE FROM files WHERE id=?", (row[0],))
        if is_private:
            store.set_state("last_import", stats)
            store.set_state("import_generation", store.state("import_generation", 0) + 1)
            store.set_state("import_incomplete", False)
    return stats
