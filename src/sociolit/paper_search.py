"""Paper-first retrieval, source-grounded evidence and stable local pagination."""
import json
import re
import secrets
import threading
import time
from collections import OrderedDict
from hashlib import sha256

from fastapi import Header, HTTPException
from pydantic import BaseModel, Field

from . import research
from .crosslanguage import CONCEPTS, expand
from .indexing import plain
from .retrieval import reciprocal_rank_fusion
from .source_links import locate
from .store import terms


class PaperQuery(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    mode: str = Field(default='auto', pattern='^(auto|fulltext|semantic|hybrid)$')
    author: str = Field(default='', max_length=100)
    year: str = Field(default='', pattern=r'^(|[0-9]{4})$')
    session: str = Field(default='', max_length=64)
    offset: int = Field(default=0, ge=0, le=100000)
    page_size: int = Field(default=10, ge=5, le=30)
    item_id: str = Field(default='', max_length=1000)


class PaperDetail(BaseModel):
    item_id: str = Field(min_length=1, max_length=1000)
    query: str = Field(default='', max_length=500)


def fingerprint(row):
    return sha256(json.dumps([row[k] for k in ('id', 'item_id', 'file_id', 'page', 'text')],
                             ensure_ascii=False).encode()).hexdigest()


def lexical(store, query, selected=None):
    """Retrieve all matching papers, up to 12 excerpts each, rather than 100 chunks.

    Materialise BM25 before the window function: SQLite FTS5 auxiliary functions
    cannot be evaluated directly inside a window or aggregate expression.
    """
    tokens = list(dict.fromkeys(terms(query)))[:64]
    if not tokens or selected == []:
        return []
    expression = ' AND '.join('"' + value + '"' for value in tokens)
    with store.connect() as db:
        scope = ''
        if selected is not None:
            db.execute('CREATE TEMP TABLE paper_scope(id TEXT PRIMARY KEY)')
            db.executemany('INSERT OR IGNORE INTO paper_scope VALUES(?)', [(i,) for i in selected])
            scope = ' AND c.item_id IN (SELECT id FROM paper_scope)'
        db.execute('CREATE TEMP TABLE paper_hits(id INTEGER PRIMARY KEY, score REAL)')
        db.execute('''INSERT INTO paper_hits SELECT c.id,bm25(chunks_fts)
            FROM chunks_fts JOIN chunks c ON c.id=chunks_fts.rowid JOIN items i ON i.id=c.item_id
            WHERE chunks_fts MATCH ? AND i.kind NOT IN ('note','annotation')''' + scope, (expression,))
        rows = db.execute('''SELECT * FROM (
            SELECT c.*,i.title,i.item_key,i.source,h.score,
            row_number() OVER(PARTITION BY c.item_id,c.kind ORDER BY h.score,c.id) AS position
            FROM paper_hits h JOIN chunks c ON c.id=h.id JOIN items i ON i.id=c.item_id)
            WHERE position<=12 ORDER BY score,id''').fetchall()
    return [dict(row) for row in rows]


def signals(query, variants):
    values = re.findall(r'[\u3400-\u9fff]{2,}|[a-zA-Z][a-zA-Z-]{2,}', query)
    for chinese, english in CONCEPTS:
        for term in [*chinese, *english]:
            if term.casefold() in query.casefold():
                values.append(term)
    for value in variants:
        values.extend(re.findall(r'[\u3400-\u9fff]{2,}|[a-zA-Z][a-zA-Z-]{2,}', value))
    # Chinese phrases separated by conjunctions remain readable in explanations.
    extra = []
    for value in values:
        if re.search(r'[\u3400-\u9fff]', value):
            extra.extend(s for s in re.split(r'[与和的及对]|影响|关系|如何|为什么', value) if len(s) >= 2)
    return list(dict.fromkeys([*values, *extra]))[:48]


def matches(text, values):
    lowered = text.casefold()
    found = []
    for value in sorted(values, key=lambda s: -len(s)):
        pattern = re.escape(value) if re.search(r'[\u3400-\u9fff]', value) else r'\b' + re.escape(value) + r'\b'
        if re.search(pattern, lowered) and not any(value in old for old in found):
            found.append(value)
    return found[:6]


def backmatter(text):
    """Conservative ranking signal, never delete or alter indexed source text."""
    if re.search(r'作者单位|责任编辑|通讯作者|作者简介|参考文献|参考书目|\bReferences\b|\bBibliography\b', text, re.I):
        return True
    citations = len(re.findall(r'(?:\b(?:19|20)\d{2}\b|\[\d+\]|［\d+］)', text))
    return citations >= 4 and (text.count('\n') >= 4 or citations >= 7)


def abstract_from_pages(db, identity):
    rows = db.execute('''SELECT file_id,page,text FROM chunks WHERE item_id=? AND kind IN ('pdf','ocr')
        AND page<=3 ORDER BY file_id,page,ordinal LIMIT 45''', (identity,)).fetchall()
    # Never join across separate PDFs or across pages; extraction provenance stays exact.
    pages = OrderedDict()
    for row in rows:
        key = (row['file_id'], row['page'])
        previous = pages.get(key, '')
        text = row['text']
        overlap = next((n for n in range(min(100, len(previous), len(text)), 19, -1)
                        if previous.endswith(text[:n])), 0)
        pages[key] = previous + text[overlap:]
    for (_, page), text in pages.items():
        match = re.search(r'(?:摘\s*要|\bAbstract\b)\s*[:：]?\s*(.{60,6000}?)(?=关\s*键\s*词|\bKeywords?\b|中图分类号)',
                          text, re.S | re.I)
        if match:
            return {'text': match.group(1).strip(), 'source': f'PDF 第 {page} 页提取（需核对）'}
    return {'text': '', 'source': '本机书目未提供摘要，PDF 首页也未识别到明确摘要段落'}


def present(store, query, rankings, info, variants):
    fused = reciprocal_rank_fusion(*rankings)
    values = signals(query, variants)
    grouped = OrderedDict()
    for rank, row in enumerate(fused):
        grouped.setdefault(row['item_id'], {'rank': rank, 'rows': []})['rows'].append(row)
    papers = []
    with store.connect() as db:
        for identity, group in grouped.items():
            item = db.execute('SELECT * FROM items WHERE id=?', (identity,)).fetchone()
            if not item or item['kind'] in ('note', 'annotation'):
                continue
            meta = json.loads(item['metadata'])
            abstract = {'text': plain(str(meta.get('abstract') or '')), 'source': 'Zotero / 来源书目摘要'}
            if not abstract['text']:
                abstract = abstract_from_pages(db, identity)
            title_hits = matches(item['title'], values)
            abstract_hits = matches(abstract['text'], values)
            candidates = [r for r in group['rows'] if r['kind'] in ('pdf', 'ocr') and r.get('page')]
            # Metadata-only semantic results can still locate direct lexical evidence within this paper.
            if not candidates:
                for variant in [query, *variants[:3]]:
                    candidates.extend(r for r in store.search(variant, 60, item_ids=[identity])
                                      if r['kind'] in ('pdf', 'ocr') and r.get('page'))
            candidates.sort(key=lambda r: (backmatter(r['text']), -len(matches(r['text'], values)),
                                           r.get('page') or 0, r['id']))
            evidence, seen = [], set()
            for row in candidates:
                key = (row['file_id'], row['page'])
                if key in seen or backmatter(row['text']):
                    continue
                seen.add(key)
                source = dict(row)
                source.pop('source', None)
                source['source_digest'] = fingerprint(row)
                source['matched_terms'] = matches(row['text'], values)
                source.update(locate(store, row['file_id'], row['page']))
                evidence.append(source)
                if len(evidence) == 3:
                    break
            # Keep source snapshots unmodified for notes, AI consent and comparison.
            representative = evidence[0] if evidence else next((r for r in group['rows'] if r['kind'] == 'metadata'), None)
            if representative:
                representative = dict(representative)
                representative.pop('source', None)
                representative['source_digest'] = fingerprint(representative)
            else:
                row = db.execute('''SELECT c.*,i.title FROM chunks c JOIN items i ON i.id=c.item_id
                    WHERE c.item_id=? AND c.kind='metadata' ORDER BY c.ordinal LIMIT 1''', (identity,)).fetchone()
                if row:
                    representative = dict(row)
                    representative['source_digest'] = fingerprint(representative)
            reasons = []
            if title_hits:
                reasons.append('题名涉及“' + '、'.join(title_hits[:3]) + '”')
            if abstract_hits:
                reasons.append('摘要出现“' + '、'.join(abstract_hits[:3]) + '”')
            body_hits = list(dict.fromkeys(t for r in evidence for t in r['matched_terms']))
            if body_hits:
                reasons.append('正文命中“' + '、'.join(body_hits[:3]) + '”，可核对下列摘录')
            if not reasons:
                reasons.append('当前所选文献；暂未发现与查询直接对应的词语' if info.get('selected_paper') else
                               '本机检索返回的候选文献，请结合摘要核对主题')
            sentences = [s.strip() for s in re.split(r'(?<=[。！？.!?])\s*', abstract['text']) if 8 <= len(s.strip()) <= 450]
            excerpt = max(sentences, key=lambda s: sum(len(t)**.5 for t in matches(s, values)), default='')
            if excerpt and not matches(excerpt, values):
                excerpt = ''
            score = (len(title_hits)*8 + len(abstract_hits)*4 + min(len(body_hits), 4)*2
                     + 12/(1 + group['rank']/10) + (2 if evidence else 0))
            papers.append({'item_id': identity, 'title': item['title'], 'authors': meta.get('authors', []),
                           'year': meta.get('year'), 'journal': meta.get('journal') or (meta.get('raw') or {}).get('publicationTitle', ''),
                           'abstract': abstract, 'relation': '；'.join(reasons) + '。',
                           'relation_excerpt': excerpt,
                           'evidence': evidence, 'representative': representative, 'rank_score': score,
                           'evidence_message': '' if evidence else '尚未定位到可靠的正文命中页；参考书目、作者单位等片段不作为主要证据。'})
    return sorted(papers, key=lambda r: (-r['rank_score'], r['item_id']))


def attach(app, store, authorize, semantic):
    sessions = OrderedDict()
    lock = threading.Lock()

    @app.post('/api/literature/paper')
    def detail(body: PaperDetail, x_sociolit_token: str | None = Header(default=None)):
        authorize(x_sociolit_token)
        with store.connect() as db:
            item = db.execute('SELECT title FROM items WHERE id=? AND kind NOT IN (\'note\',\'annotation\')', (body.item_id,)).fetchone()
            rows = [dict(r) for r in db.execute('''SELECT c.*,i.title,i.source,i.item_key FROM chunks c JOIN items i ON i.id=c.item_id
                WHERE c.item_id=? AND c.kind='metadata' ORDER BY c.ordinal LIMIT 12''', (body.item_id,))]
        if not item or not rows:
            raise HTTPException(404, '文献已不在当前资料库中，请重新同步。')
        query = body.query or item['title']
        rankings = [rows, lexical(store, query, [body.item_id])]
        papers = present(store, query, rankings, {'selected_paper': True}, expand(query))
        paper = papers[0]
        paper['reading'] = research.reading_states(store, [body.item_id]).get(body.item_id, {})
        return paper

    def stamp():
        with store.connect() as db:
            c = db.execute('SELECT count(*),max(id) FROM chunks').fetchone()
        return (store.state('import_generation', 0), c[0], c[1])

    @app.post('/api/search/papers')
    def search(body: PaperQuery, x_sociolit_token: str | None = Header(default=None)):
        authorize(x_sociolit_token)
        request = body.model_dump(exclude={'session', 'offset', 'page_size'})
        current = stamp()
        if body.session:
            with lock:
                cached = sessions.get(body.session)
            if not cached or time.monotonic()-cached['time'] > 1200 or cached['stamp'] != current or cached['request'] != request:
                raise HTTPException(409, '检索结果已过期或资料库已变化，请重新检索。')
        else:
            if body.offset:
                raise HTTPException(400, '请先从第一页开始检索。')
            selected = None
            if body.author or body.year or body.item_id:
                with store.connect() as db:
                    records = db.execute('''SELECT id FROM items WHERE
                        instr(lower(COALESCE(json_extract(metadata,'$.authors'),'')),lower(?)) > 0
                        AND (?='' OR CAST(json_extract(metadata,'$.year') AS TEXT)=?)
                        AND (?='' OR id=?)''', (body.author, body.year, body.year, body.item_id, body.item_id)).fetchall()
                selected = [row['id'] for row in records]
            variants = expand(body.query) if body.mode == 'auto' else []
            info = {'semantic': False, 'semantic_scope': '', 'expanded_queries': variants,
                    'message': '按文献合并结果；摘要与正文优先，参考书目、单位和编辑信息降权。'}
            rankings = []
            try:
                if body.mode != 'semantic':
                    rankings = [lexical(store, q, selected) for q in [body.query, *variants]]
                if body.mode in ('auto', 'semantic', 'hybrid') and selected != []:
                    try:
                        found, scope = semantic(body.query, selected, body.mode)
                        rankings.append(found)
                        info.update(semantic=True, semantic_scope=scope)
                    except (RuntimeError, ValueError) as exc:
                        if body.mode == 'semantic':
                            raise
                        info['message'] += ' 本次语义未参与：' + str(exc)[:180]
                papers = present(store, body.query, rankings, info, variants)
            except (RuntimeError, ValueError) as exc:
                raise HTTPException(400, str(exc)) from exc
            research.remember_search(store, request | {'item_id': ''})
            identity = secrets.token_hex(16)
            cached = {'papers': papers, 'info': info, 'request': request, 'stamp': current, 'time': time.monotonic()}
            with lock:
                sessions[identity] = cached
                while len(sessions) > 6:
                    sessions.popitem(last=False)
            body.session = identity
        rows = cached['papers'][body.offset:body.offset + body.page_size]
        reading = research.reading_states(store, [r['item_id'] for r in rows])
        rows = [dict(r, reading=reading.get(r['item_id'], {})) for r in rows]
        return {'papers': rows, 'total': len(cached['papers']), 'offset': body.offset, 'page_size': body.page_size,
                'session': body.session, 'has_more': body.offset + len(rows) < len(cached['papers']),
                'search_info': cached['info']}
