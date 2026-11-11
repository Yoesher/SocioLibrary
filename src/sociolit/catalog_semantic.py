"""One multilingual vector per bibliography entry, separate from PDF pilot vectors."""
import json
import math
from hashlib import sha256

from filelock import FileLock


def initialize(store):
    with store.connect() as db:
        db.execute('''CREATE TABLE IF NOT EXISTS catalog_vectors (
            item_id TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
            model TEXT NOT NULL,fingerprint TEXT NOT NULL,embedding TEXT NOT NULL,
            PRIMARY KEY(item_id,model))''')


def content(row):
    metadata = json.loads(row['metadata'])
    return '\n'.join([row['title'], '; '.join(metadata.get('authors') or []),
                      str(metadata.get('abstract') or '')[:1800], ' '.join(metadata.get('tags') or [])])[:2400]


def fingerprint(text):
    return sha256(('catalog-v1:' + text).encode()).hexdigest()


def status(store, model):
    with store.connect() as db:
        rows = db.execute('''SELECT i.id,i.title,i.metadata,v.fingerprint FROM items i
            LEFT JOIN catalog_vectors v ON v.item_id=i.id AND v.model=?
            WHERE i.kind NOT IN ('note','annotation')''', (model,)).fetchall()
    done = sum(row['fingerprint'] == fingerprint(content(row)) for row in rows)
    return {'done': done, 'total': len(rows), 'ready': bool(rows) and done == len(rows)}


def build(store, embedder, progress=None):
    progress = progress or (lambda *_: None)
    indexed = 0
    with FileLock(str(store.directory / 'library.lock'), timeout=1):
        if store.state('import_incomplete', False):
            raise RuntimeError('请完成 Zotero 同步后再建立全库书目索引。')
        with store.connect() as db:
            rows = db.execute('''SELECT i.id,i.title,i.metadata,v.fingerprint FROM items i
                LEFT JOIN catalog_vectors v ON v.item_id=i.id AND v.model=?
                WHERE i.kind NOT IN ('note','annotation') ORDER BY i.id''', (embedder.key,)).fetchall()
        pending = [(row, content(row)) for row in rows if row['fingerprint'] != fingerprint(content(row))]
        progress('catalog_embedding', 0, len(pending))
        for start in range(0, len(pending), 16):
            batch = pending[start:start+16]
            vectors = embedder.encode([text for row, text in batch])
            if len(vectors) != len(batch):
                raise ValueError('书目语义模型返回数量不匹配。')
            values = []
            for (row, text), vector in zip(batch, vectors, strict=True):
                if not vector or not any(vector) or not all(math.isfinite(float(value)) for value in vector):
                    raise ValueError('书目语义模型返回无效向量。')
                values.append((row['id'], embedder.key, fingerprint(text), json.dumps(vector)))
            with store.connect() as db:
                # A cooperating importer holds the same file lock; this check
                # also refuses changed content from an unexpected external writer.
                for row, text in batch:
                    current = db.execute('SELECT title,metadata FROM items WHERE id=?', (row['id'],)).fetchone()
                    if not current or content(current) != text:
                        raise RuntimeError('构建时书目发生变化，请同步后继续。')
                db.executemany('INSERT OR REPLACE INTO catalog_vectors VALUES(?,?,?,?)', values)
            indexed += len(values)
            progress('catalog_embedding', indexed, len(pending))
        store.set_state('catalog_semantic', {'model': embedder.key, 'version': 1})
    return {'indexed': indexed, 'items': len(rows), 'scope': '全库题名、摘要与标签（不含全文）'}


def search(store, embedder, query, item_ids=None, limit=100):
    if store.state('import_incomplete', False):
        raise RuntimeError('同步尚未完成，全库书目语义暂不可用。')
    current = status(store, embedder.key)
    if not current['ready']:
        raise RuntimeError(f"全库书目语义索引尚未齐备（{current['done']}/{current['total']}篇），请在资料整理中建立或继续。")
    vector = embedder.encode([query], query=True)[0]
    if not vector or not any(vector) or not all(math.isfinite(float(value)) for value in vector):
        raise ValueError('查询向量无效。')
    norm = math.sqrt(sum(value*value for value in vector))
    selected = set(item_ids) if item_ids is not None else None
    with store.connect() as db:
        rows = db.execute('''SELECT i.id AS item_id,v.embedding,c.id FROM catalog_vectors v
            JOIN items i ON i.id=v.item_id JOIN chunks c ON c.id=(
              SELECT id FROM chunks WHERE item_id=i.id AND kind='metadata' ORDER BY ordinal,id LIMIT 1)
            WHERE v.model=?''', (embedder.key,)).fetchall()
        scores = []
        for row in rows:
            if selected is not None and row['item_id'] not in selected:
                continue
            candidate = json.loads(row['embedding'])
            if len(candidate) != len(vector) or not all(math.isfinite(float(value)) for value in candidate):
                raise RuntimeError('书目向量格式或维度变化，请重建索引。')
            denominator = norm * math.sqrt(sum(value*value for value in candidate))
            score = sum(a*b for a, b in zip(vector, candidate, strict=True))/denominator if denominator else 0
            scores.append((score, row['id']))
        output = []
        for score, identity in sorted(scores, reverse=True)[:limit]:
            row = dict(db.execute('''SELECT c.*,i.title,i.item_key,i.source FROM chunks c
                JOIN items i ON i.id=c.item_id WHERE c.id=?''', (identity,)).fetchone())
            row['score'] = score
            row['retrieval_kind'] = 'catalog_semantic'
            output.append(row)
    return output


def graph_candidates(store, seed='', selected=None, limit=12):
    """Reuse passage vectors; no model loading, inference or provider request."""
    state = store.state('catalog_semantic', {})
    model = state.get('model') if isinstance(state, dict) else None
    if not model or not status(store, model)['ready']:
        return []
    if selected is not None and not selected:
        return []
    with store.connect() as db:
        query = 'SELECT item_id,embedding FROM catalog_vectors WHERE model=?'
        parameters = [model]
        if selected is not None:
            query += ' AND item_id IN (' + ','.join('?' for _ in selected) + ')'
            parameters.extend(selected)
        rows = db.execute(query, parameters).fetchall()
    vectors = {}
    allowed = set(selected) if selected is not None else None
    for row in rows:
        if allowed is not None and row['item_id'] not in allowed:
            continue
        vector = json.loads(row['embedding'])
        norm = math.sqrt(sum(value*value for value in vector))
        if norm and all(math.isfinite(float(value)) for value in vector):
            vectors[row['item_id']] = [value/norm for value in vector]
    pairs = []
    for left in ([seed] if seed in vectors else [] if seed else vectors):
        for right in vectors:
            if left == right or (not seed and right < left):
                continue
            a, b = vectors[left], vectors[right]
            if len(a) != len(b):
                continue
            score = sum(x*y for x, y in zip(a, b, strict=True))
            if score >= .5:
                pairs.append((left, right, score))
    return sorted(pairs, key=lambda row: (-row[2], row[0], row[1]))[:limit]
