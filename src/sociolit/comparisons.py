"""Persistent, reviewable comparison matrices with immutable evidence snapshots."""
import copy
import csv
import io
import json
import re
import uuid
from datetime import datetime, timezone
from html import escape

from .ai_context import evidence, fingerprint
from .literature import get_item

FIELDS = {"question": "研究问题", "theory": "理论视角", "data": "数据与对象", "methods": "研究方法",
          "findings": "主要发现", "limits": "局限与适用范围"}


def initialize(store):
    with store.connect() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS literature_comparisons (
            id TEXT PRIMARY KEY,title TEXT NOT NULL,body_json TEXT NOT NULL,revision TEXT NOT NULL,
            updated TEXT NOT NULL,archived INTEGER NOT NULL DEFAULT 0)""")


def _insert(store, title, data):
    identity, revision = uuid.uuid4().hex, uuid.uuid4().hex
    with store.connect() as db:
        db.execute("INSERT INTO literature_comparisons VALUES(?,?,?,?,?,0)",
                   (identity, title, json.dumps(data, ensure_ascii=False), revision, datetime.now(timezone.utc).isoformat()))
    return get(store, identity)


def create(store, title, selections):
    sources = evidence(store, selections)
    papers, identities = [], []
    with store.connect() as db:
        for selection, source in zip(selections, sources, strict=True):
            item_id = db.execute("SELECT item_id FROM chunks WHERE id=?", (selection["chunk_id"],)).fetchone()[0]
            if item_id not in identities:
                item = get_item(store, item_id)
                identities.append(item_id)
                papers.append({"code": f"P{len(papers)+1}", **{key: item[key] for key in
                               ("id", "title", "authors", "year", "journal", "doi")}})
            source["paper"] = f"P{identities.index(item_id)+1}"
            source["selection"] = selection
    if not 2 <= len(papers) <= 6:
        raise ValueError("每张对照表需要 2–6 篇不同文献，合计最多 8 个片段。")
    title = title.strip()
    if not 1 <= len(title) <= 120:
        raise ValueError("请填写 1–120 字的对照表名称。")
    cells = {paper["code"]: {key: {"text": "", "citations": [], "reviewed": False} for key in FIELDS}
             for paper in papers}
    return _insert(store, title, {"papers": papers, "sources": sources, "cells": cells, "origin": "manual"})


def _load(store, identity):
    with store.connect() as db:
        row = db.execute("SELECT * FROM literature_comparisons WHERE id=?", (identity,)).fetchone()
    if not row:
        raise ValueError("对照表不存在。")
    return row, json.loads(row["body_json"])


def get(store, identity):
    row, data = _load(store, identity)
    with store.connect() as db:
        for source in data["sources"]:
            selection = source["selection"]
            chunk = db.execute("SELECT * FROM chunks WHERE id=?", (selection["chunk_id"],)).fetchone()
            source["current"] = bool(chunk and fingerprint(chunk) == selection["digest"])
            if not source["current"]:
                source["pdf_url"] = None
    return {"id": row["id"], "title": row["title"], "revision": row["revision"],
            "updated": row["updated"], "archived": bool(row["archived"]), "fields": FIELDS, **data}


def list_boards(store, include_archived=False):
    with store.connect() as db:
        rows = db.execute("""SELECT id,title,revision,updated,archived FROM literature_comparisons
            WHERE (?=1 OR archived=0) ORDER BY updated DESC LIMIT 200""", (int(include_archived),)).fetchall()
    return [dict(row) for row in rows]


def validate_cells(cells, papers, sources, *, generated=False):
    if not isinstance(cells, dict) or set(cells) != {paper["code"] for paper in papers}:
        raise ValueError("对照表的文献列不完整或包含未知文献。")
    labels = {source["label"]: source["paper"] for source in sources}
    result = {}
    for paper, fields in cells.items():
        if not isinstance(fields, dict) or set(fields) != set(FIELDS):
            raise ValueError("对照表必须包含全部六个维度。")
        result[paper] = {}
        for key, cell in fields.items():
            if not isinstance(cell, dict) or set(cell) - {"text", "citations", "reviewed"}:
                raise ValueError("对照表单元格格式无效。")
            text, citations = cell.get("text"), cell.get("citations")
            if (not isinstance(text, str) or len(text) > 2000 or not isinstance(citations, list)
                    or len(citations) > 8 or any(not isinstance(label, str) for label in citations)
                    or len(set(citations)) != len(citations)):
                raise ValueError("每格最多 2000 字，出处只能使用本次片段编号。")
            if any(labels.get(label) != paper for label in citations):
                raise ValueError("单元格引用了不存在或属于另一篇文献的片段，未保存草稿。")
            if generated and not citations and text != "材料未提供":
                raise ValueError("AI 单元格缺少出处；无依据时必须填写“材料未提供”，未保存草稿。")
            if type(cell.get("reviewed", False)) is not bool:
                raise ValueError("核对状态无效。")
            result[paper][key] = {"text": text, "citations": citations,
                                  "reviewed": False if generated else cell.get("reviewed", False)}
    return result


def save(store, identity, revision, title, cells):
    row, data = _load(store, identity)
    title = title.strip()
    if row["revision"] != revision:
        raise ValueError("对照表已在其他操作中变化，请刷新后再保存，避免覆盖。")
    if not 1 <= len(title) <= 120:
        raise ValueError("对照表名称应为 1–120 字。")
    data["cells"] = validate_cells(cells, data["papers"], data["sources"])
    with store.connect() as db:
        cursor = db.execute("""UPDATE literature_comparisons SET title=?,body_json=?,revision=?,updated=?
            WHERE id=? AND revision=?""", (title, json.dumps(data, ensure_ascii=False), uuid.uuid4().hex,
            datetime.now(timezone.utc).isoformat(), identity, revision))
        if not cursor.rowcount:
            raise ValueError("对照表已变化，未覆盖原表。")
    return get(store, identity)


def archive(store, identity, revision, archived):
    with store.connect() as db:
        cursor = db.execute("UPDATE literature_comparisons SET archived=?,revision=? WHERE id=? AND revision=?",
                            (int(archived), uuid.uuid4().hex, identity, revision))
        if not cursor.rowcount:
            raise ValueError("对照表已变化，请刷新后再归档或恢复。")
    return get(store, identity)


def adopt_ai(store, board, cells, model, connection):
    if get(store, board["id"])["revision"] != board["revision"]:
        raise ValueError("原表已变化，请重新生成 AI 草稿；未覆盖任何表格。")
    _, data = _load(store, board["id"])
    data = copy.deepcopy(data)
    data["cells"] = validate_cells(cells, data["papers"], data["sources"], generated=True)
    data.update(origin="ai_draft", model=model, connection=connection)
    return _insert(store, "AI 草稿 · " + board["title"][:110], data)


def parse_ai(text, board):
    # No repair calls or automatic second paid attempt.
    text = text.strip()
    if text.startswith("```json\n") and text.endswith("```"):
        text = text[8:-3].strip()
    try:
        def unique_object(pairs):
            value = {}
            for key, item in pairs:
                if key in value:
                    raise ValueError("duplicate key")
                value[key] = item
            return value
        cells = json.loads(text, object_pairs_hook=unique_object)
    except ValueError as exc:
        raise ValueError("AI 没有返回完整 JSON 对照表，原表未改变；请调整输出上限后重新预览。") from exc
    return validate_cells(cells, board["papers"], board["sources"], generated=True)


def export(store, identity, format, revision=None):
    board = get(store, identity)
    if revision is not None and board["revision"] != revision:
        raise ValueError("对照表已变化，请刷新后再导出。")
    if format == "csv":
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(["对照表", "状态", "文献", "作者", "年份", *FIELDS.values()])
        for paper in board["papers"]:
            values = [board["title"], "AI 草稿，需核对" if board["origin"] == "ai_draft" else "人工对照",
                      paper["title"], "、".join(paper.get("authors") or []), str(paper.get("year") or "")]
            for key in FIELDS:
                cell = board["cells"][paper["code"]][key]
                values.append(cell["text"] + " " + " ".join("[" + label + "]" for label in cell["citations"]) +
                              (" 【已核对】" if cell["reviewed"] else " 【待核对】"))
            writer.writerow([_csv_safe(value) for value in values])
        writer.writerow([])
        writer.writerow(["来源编号", "所属文献", "题名", "PDF页序", "文件页标签", "类型", "原文快照"])
        for source in board["sources"]:
            writer.writerow([_csv_safe(str(value or "")) for value in (source["label"], source["paper"],
                source["title"], source["page"], source["page_label"], source["kind"], source["text"])])
        return output.getvalue()
    if format != "md":
        raise ValueError("只支持 Markdown 或 CSV 导出。")
    def cell_text(value):
        text = escape(str(value), quote=False).replace("\\", "\\\\")
        return re.sub(r"([|`*\[\]_()])", r"\\\1", text).replace("\n", "<br>")
    lines = ["# " + cell_text(board["title"]), "", "AI 草稿，未经人工核对。" if board["origin"] == "ai_draft" else "人工文献对照表。",
             "出处为创建时保存的片段快照；页序不等于刊物印刷页码。", "",
             "| 维度 | " + " | ".join(cell_text(paper["title"]) for paper in board["papers"]) + " |",
             "| --- | " + " | ".join("---" for _ in board["papers"]) + " |"]
    for key, label in FIELDS.items():
        values = []
        for paper in board["papers"]:
            cell = board["cells"][paper["code"]][key]
            text = cell["text"] or "待填写"
            values.append(cell_text(text) + " " + " ".join("[" + value + "]" for value in cell["citations"]) +
                          ("（已核对）" if cell["reviewed"] else "（待核对）"))
        lines.append("| " + label + " | " + " | ".join(values) + " |")
    lines.extend(["", "## 来源快照", ""])
    for source in board["sources"]:
        lines.extend(["### [" + source["label"] + "] " + cell_text(source["title"]),
                      "PDF 页序：" + str(source["page"] or "未提供") + "；类型：" + source["kind"], ""])
        fence = "`" * max(3, max((len(match) + 1 for match in re.findall(r"`+", source["text"])), default=3))
        lines.extend([fence, source["text"], fence, ""])
    return "\n".join(lines)


def _csv_safe(value):
    return "'" + value if value.lstrip(" \t\r\n\ufeff").startswith(("=", "+", "-", "@")) else value
