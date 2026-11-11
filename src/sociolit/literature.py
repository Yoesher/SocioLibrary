"""Local literature suggestions; scores are retrieval signals, not scientific judgments."""
import json
import math
import re
from collections import Counter
from difflib import SequenceMatcher
from urllib.parse import quote

from .ai_context import fingerprint
from .store import terms

STOP = set("研究 社会 问题 分析 影响 关系 本文 以及 结果 通过 关于 the and with from this that study research analysis using".split())


def get_item(store, identity):
    with store.connect() as db:
        row = db.execute("SELECT id,title,kind,metadata FROM items WHERE id=?", (identity,)).fetchone()
    if not row or row["kind"] in ("note", "annotation"):
        raise ValueError("文献已不在资料库，请重新同步或检索。")
    meta = json.loads(row["metadata"])
    tags = meta.get("tags") or []
    tags = [str(tag) for tag in tags if isinstance(tag, str)] if isinstance(tags, list) else []
    return {"id": row["id"], "title": row["title"], "authors": meta.get("authors", []),
            "year": meta.get("year"), "abstract": str(meta.get("abstract") or ""),
            "tags": tags, "doi": str(meta.get("doi") or ""), "journal": str(meta.get("journal") or "")}


def signature(item):
    counter = Counter()
    for value, weight in ((item["title"][:1000], 4), (" ".join(item.get("tags") or [])[:1000], 3),
                          ((item.get("abstract") or "")[:4000], 1)):
        counts = Counter(term for term in terms(value) if term not in STOP and
                         (re.fullmatch(r"[\u3400-\u9fff]{2}", term) or re.fullmatch(r"[a-z][a-z0-9]{2,}", term)))
        for term, count in counts.items():
            counter[term] += min(count, 3) * weight
    for tag in (item.get("tags") or [])[:100]:
        if tag.strip():
            counter["tag:" + tag.strip().casefold()] += 5
    return counter


def same_work(left, right):
    def norm(value):
        return re.sub(r"\W", "", value).casefold()
    return (bool(left.get("doi") and left["doi"].casefold() == (right.get("doi") or "").casefold())
            or norm(left["title"]) == norm(right["title"]))


def recommend_metadata(store, identity, limit=10):
    seed = get_item(store, identity)
    weights = signature(seed)
    tokens = [term for term, _ in sorted(weights.items(), key=lambda pair: (-pair[1], pair[0]))
              if not term.startswith("tag:")][:32]
    if not weights:
        return {"seed": seed, "mode": "metadata", "scope": "本机已导入书目信息", "results": [],
                "message": "题名、摘要或标签信息不足，暂不能生成相关候选。"}
    expression = " OR ".join('"' + term + '"' for term in tokens)
    with store.connect() as db:
        rows = db.execute("""SELECT c.item_id FROM chunks_fts JOIN chunks c ON c.id=chunks_fts.rowid
            WHERE chunks_fts MATCH ? AND c.kind='metadata' AND c.item_id<>?
            ORDER BY bm25(chunks_fts) LIMIT 1200""", (expression, identity)).fetchall() if tokens else []
        tags = list(dict.fromkeys(tag.casefold() for tag in seed.get("tags") or []))[:32]
        tagged = db.execute("""SELECT DISTINCT i.id FROM items i JOIN json_each(i.metadata,'$.tags') tag
            WHERE i.id<>? AND i.kind NOT IN ('note','annotation') AND lower(CAST(tag.value AS TEXT)) IN (""" +
            ",".join("?" for _ in tags) + ") ORDER BY i.id LIMIT 100", (identity, *tags)).fetchall() if tags else []
    identities = list(dict.fromkeys(row[0] for row in [*tagged, *rows]))[:300]
    seed_norm = math.sqrt(sum(value * value for value in weights.values()))
    output = []
    for candidate_id in identities:
        candidate = get_item(store, candidate_id)
        if same_work(seed, candidate) or any(same_work(candidate, previous) for previous in output):
            continue
        vector = signature(candidate)
        overlap = sorted(set(weights) & set(vector), key=lambda term: (-weights[term] * vector[term], term))
        denominator = seed_norm * math.sqrt(sum(value * value for value in vector.values()))
        score = sum(weights[term] * vector[term] for term in overlap) / denominator if denominator else 0
        if score < 0.05:
            continue
        matches = SequenceMatcher(None, seed["title"], candidate["title"], autojunk=False).get_matching_blocks()
        shared = [seed["title"][match.a:match.a+match.size].strip() for match in matches if match.size >= 2]
        shared = [text for text in shared if text not in STOP and text not in {'的影响', '的研究', '影响因素'}
                  and len(re.findall(r'[\w\u3400-\u9fff]', text)) >= 2][:4]
        visible = [term for term in overlap if not term.startswith("tag:")]
        reason = "题名共同文字：" + "、".join(shared) if shared else "共同字词片段：" + "、".join(visible[:6])
        if not shared and not visible:
            reason = "共享 Zotero 标签"
        candidate.update(score=round(score, 5), reasons=[reason])
        tags = sorted(set(seed.get("tags") or []) & set(candidate.get("tags") or []))
        if tags:
            candidate["reasons"].append("共同标签：" + "、".join(tags[:4]))
        output.append(candidate)
    output.sort(key=lambda row: (-row["score"], row["id"]))
    return {"seed": seed, "mode": "metadata", "scope": "本机已导入书目信息", "results": output[:limit],
            "message": "按题名、摘要和标签的共同词语排序；候选最多 300 篇，分数不代表研究质量或理论一致。"}


def recommend_semantic(store, identity, embedder, *, item_ids=None, scope="全部语义索引", limit=10):
    from .semantic import search_vectors
    seed = get_item(store, identity)
    query = (seed["title"] + "\n" + (seed.get("abstract") or "") + "\n" + " ".join(seed.get("tags") or []))[:2000]
    rows = search_vectors(store, embedder, query, limit=200, item_ids=item_ids, exclude_item_id=identity)
    seen, output = set(), []
    for row in rows:
        if row["item_id"] in seen or row["kind"] not in ("pdf", "ocr", "metadata") or row["score"] <= 0:
            continue
        seen.add(row["item_id"])
        candidate = get_item(store, row["item_id"])
        if same_work(seed, candidate) or any(same_work(candidate, previous) for previous in output):
            continue
        candidate.update(score=round(row["score"], 5), reasons=["种子题名与摘要和候选片段在本机模型中的语义接近"],
                         excerpt=row["text"][:500], page=row["page"])
        output.append(candidate)
        if len(output) == limit:
            break
    return {"seed": seed, "mode": "semantic", "scope": scope, "results": output,
            "message": "只使用已有、完整且有效的本机语义索引；不自动构建索引或调用云端 API。"}


def excerpts(store, identity, query=""):
    item = get_item(store, identity)
    if query.strip():
        rows = store.search(query.strip(), item_ids=[identity], limit=20)
    else:
        with store.connect() as db:
            rows = [dict(row) for row in db.execute("""SELECT c.*,i.title FROM chunks c JOIN items i ON i.id=c.item_id
                WHERE c.item_id=? ORDER BY CASE c.kind WHEN 'pdf' THEN 0 WHEN 'ocr' THEN 1 ELSE 2 END,
                c.page,c.ordinal,c.id LIMIT 20""", (identity,))]
    for row in rows:
        row["source_digest"] = fingerprint(row)
        row["title"] = item["title"]
        row["authors"], row["year"] = item["authors"], item["year"]
        row["pdf_url"] = "/api/pdf/" + quote(row["file_id"], safe="") + "#page=" + str(row["page"]) \
            if row["file_id"] and row["page"] else None
        for key in ("source", "item_key", "score"):
            row.pop(key, None)
    return {"item": item, "chunks": rows}
