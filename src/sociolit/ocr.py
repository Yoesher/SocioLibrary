"""Windows OCR creates derived page text only; original PDFs remain unchanged."""
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import pypdfium2 as pdfium
from filelock import FileLock

from .indexing import file_digest, split_text


def windows_ocr(request):
    if sys.platform != "win32":
        raise RuntimeError("此版本 OCR 只支持 Windows。")
    executable = Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    script = Path(__file__).with_name("ocr.ps1").read_text(encoding="utf-8")
    try:
        result = subprocess.run([str(executable), "-NoProfile", "-NonInteractive", "-Command", script],
                                input=json.dumps(request, ensure_ascii=False), encoding="utf-8", capture_output=True,
                                timeout=90, creationflags=subprocess.CREATE_NO_WINDOW)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("单页 OCR 超时，已完成的页面会保留，可稍后继续。") from exc
    if result.returncode:
        raise RuntimeError("Windows OCR 不可用或缺少所选语言包，请在 Windows 语言设置中安装文字识别组件。")
    return json.loads(result.stdout.lstrip("\ufeff").strip())


def recognize_image(path, language):
    return windows_ocr({"action": "recognize", "path": str(Path(path).resolve()), "language": language})["text"]


def initialize(store):
    with store.connect() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS ocr_pages (
            file_id TEXT NOT NULL REFERENCES files(id) ON DELETE CASCADE,
            page INTEGER NOT NULL, language TEXT NOT NULL, text TEXT NOT NULL,
            PRIMARY KEY(file_id,page))""")


def process_ocr(store, roots, language, *, max_pages=20, progress=None, recognizer=recognize_image):
    if not 1 <= max_pages <= 100:
        raise ValueError("每次 OCR 页数必须为 1–100。")
    roots = [Path(root).resolve() for root in roots]
    progress = progress or (lambda *args: None)
    initialize(store)
    done = 0
    with FileLock(str(store.directory / "library.lock"), timeout=1):
        with store.connect() as db:
            files = db.execute("SELECT * FROM files WHERE status='needs_ocr' OR (status='indexed' AND detail LIKE 'No extractable text on PDF pages:%') ORDER BY id").fetchall()
        for row in files:
            path = Path(row["path"]).resolve()
            if not path.is_file() or path.suffix.lower() != ".pdf" or not any(path.is_relative_to(root) for root in roots):
                continue
            if path.stat().st_size > 100 * 1024 * 1024:
                continue
            digest = file_digest(path)
            if row["sha256"] != "pdfium-v1:" + digest:
                raise RuntimeError("PDF 已变化，请先同步 Zotero 后再识别。")
            with store.connect() as db:
                attempted = {r[0] for r in db.execute("SELECT page FROM ocr_pages WHERE file_id=?", (row["id"],))}
                native = {r[0] for r in db.execute("SELECT DISTINCT page FROM chunks WHERE file_id=? AND kind='pdf'", (row["id"],))}
            doc = pdfium.PdfDocument(path)
            try:
                if len(doc) > 3000:
                    continue
                for index in range(len(doc)):
                    number = index + 1
                    if number in attempted or number in native:
                        continue
                    if done >= max_pages:
                        return {"pages": done, "may_have_more": True}
                    page = doc[index]
                    try:
                        scale = min(2.5, 2400 / max(page.get_width(), page.get_height()))
                        bitmap = page.render(scale=scale)
                        try:
                            with tempfile.TemporaryDirectory(prefix="sociolit-ocr-") as temp:
                                image_path = Path(temp) / "page.png"
                                image = bitmap.to_pil()
                                try:
                                    image.save(image_path)
                                finally:
                                    image.close()
                                text = recognizer(image_path, language)
                        finally:
                            bitmap.close()
                    finally:
                        page.close()
                    # Windows OCR often inserts spaces between adjacent CJK characters.
                    # Remove horizontal inter-character gaps so Chinese bigram search remains usable.
                    text = re.sub(r"(?<=[\u3400-\u9fff])[ \t]+(?=[\u3400-\u9fff])", "", text)
                    if len(text) > 2_000_000:
                        raise RuntimeError("OCR 输出过长，已停止处理。")
                    if file_digest(path) != digest:
                        raise RuntimeError("识别期间 PDF 已变化，请重新同步后继续。")
                    with store.connect() as db:
                        db.execute("INSERT INTO ocr_pages VALUES(?,?,?,?)", (row["id"], number, language, text))
                        for ordinal, chunk in enumerate(split_text(text)):
                            store.add_chunk(db, item_id=row["item_id"], text=chunk, kind="ocr", ordinal=ordinal,
                                            file_id=row["id"], page=number, page_label=doc.get_page_label(index) or str(number))
                    done += 1
                    progress("ocr", done, max_pages)
            finally:
                doc.close()
        return {"pages": done, "may_have_more": False}
