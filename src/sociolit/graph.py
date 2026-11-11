"""Local explanatory relationships; inferred links are never citation assertions."""
import json
import math
import re
import uuid
from collections import Counter
from datetime import datetime, timezone

from .crosslanguage import CONCEPTS, expand
from .literature import get_item

TYPES = {'related': '相关', 'theory': '理论对话', 'contrast': '结论分歧', 'methods': '方法可比', 'cites': '引用（本人确认）'}


def title_terms(title):
    title = title.casefold()
    stop = {'the', 'and', 'from', 'with', 'for', 'into', 'among', 'between', 'evidence', 'study', 'effect', 'effects'}
    words = [word.removesuffix('s') if len(word) > 5 else word for word in re.findall(r'[a-z]{3,}', title) if word not in stop]
    terms = set(words) | {' '.join(words[i:i+2]) for i in range(len(words)-1)}
    for run in re.findall(r'[\u3400-\u9fff]+', title):
        terms.update(run[i:i+2] for i in range(len(run)-1))
    for chinese, english in CONCEPTS:
        if any(word in title for word in chinese) or any(re.search(r'\b'+re.escape(word)+r'\b', title) for word in english):
            terms.add('术语:' + chinese[0])
    return terms


def initialize(store):
    with store.connect() as db:
        db.execute('''CREATE TABLE IF NOT EXISTS literature_links (
            id TEXT PRIMARY KEY,source_id TEXT NOT NULL,target_id TEXT NOT NULL,kind TEXT NOT NULL,
            note TEXT NOT NULL,snapshots TEXT NOT NULL,revision TEXT NOT NULL,archived INTEGER NOT NULL DEFAULT 0,
            updated TEXT NOT NULL)''')
        db.execute('CREATE INDEX IF NOT EXISTS links_source_idx ON literature_links(source_id,archived)')
        db.execute('CREATE INDEX IF NOT EXISTS links_target_idx ON literature_links(target_id,archived)')


def node(item):
    return {key: item.get(key, [] if key in ('authors', 'tags') else '') for key in
            ('id', 'title', 'authors', 'year', 'tags', 'doi')} | {'current': True}


def create_link(store, source, target, kind, note):
    if source == target or kind not in TYPES or len(note) > 1000:
        raise ValueError('请选择两篇不同文献和有效关系类型；说明最多1000字。')
    snapshots = [node(get_item(store, identity)) for identity in (source, target)]
    if kind != 'cites' and source > target:
        source, target = target, source
        snapshots.reverse()
    with store.connect() as db:
        if db.execute('SELECT 1 FROM literature_links WHERE source_id=? AND target_id=? AND kind=? AND archived=0',
                      (source, target, kind)).fetchone():
            raise ValueError('这条关系已经存在，请保留原关系或先归档。')
        identity, revision = uuid.uuid4().hex, uuid.uuid4().hex
        db.execute('INSERT INTO literature_links VALUES(?,?,?,?,?,?,?,0,?)',
                   (identity, source, target, kind, note.strip(), json.dumps(snapshots, ensure_ascii=False),
                    revision, datetime.now(timezone.utc).isoformat()))
    return {'id': identity, 'revision': revision}


def archive(store, identity, revision, value):
    with store.connect() as db:
        row = db.execute('SELECT * FROM literature_links WHERE id=?', (identity,)).fetchone()
        if not row or row['revision'] != revision:
            raise ValueError('关系已变化，请刷新后再操作。')
        if not value and db.execute('''SELECT 1 FROM literature_links WHERE source_id=? AND target_id=?
            AND kind=? AND archived=0 AND id<>?''',
            (row['source_id'], row['target_id'], row['kind'], identity)).fetchone():
            raise ValueError('已有同类型关系，未恢复重复项。')
        db.execute('UPDATE literature_links SET archived=?,revision=? WHERE id=?',
                   (int(value), uuid.uuid4().hex, identity))
    return {'saved': True}


def catalog(store, query='', limit=30):
    with store.connect() as db:
        rows = db.execute("SELECT id,title,metadata FROM items WHERE kind NOT IN ('note','annotation') ORDER BY title").fetchall()
    values = []
    for row in rows:
        metadata = json.loads(row['metadata'])
        text = (row['title'] + ' ' + ' '.join(metadata.get('tags') or [])).casefold()
        if query.casefold() in text:
            values.append(node({**metadata, 'id': row['id'], 'title': row['title']}))
        if len(values) == limit:
            break
    return values


def build(store, query='', seed='', limit=50, include_auto=True, include_archived=False):
    if not 10 <= limit <= 80 or len(query) > 200 or len(seed) > 1000:
        raise ValueError('图谱最多80篇；检索条件无效。')
    with store.connect() as db:
        all_items = db.execute("SELECT id,title,metadata FROM items WHERE kind NOT IN ('note','annotation') ORDER BY title").fetchall()
        links = [dict(r) for r in db.execute('SELECT * FROM literature_links WHERE (? OR archived=0) ORDER BY updated DESC LIMIT 1001',
                                           (int(include_archived),))]
        boards = db.execute('SELECT id,title,body_json FROM literature_comparisons WHERE archived=0 ORDER BY updated DESC LIMIT 200').fetchall()
    all_nodes = {row['id']: node({**json.loads(row['metadata']), 'id': row['id'], 'title': row['title']}) for row in all_items}
    terms = [query.casefold(), *(term.casefold() for term in expand(query))] if query else []
    selected = []
    if seed:
        if seed not in all_nodes:
            raise ValueError('当前书目中找不到中心文献，请重新选择。')
        selected.append(seed)
        for link in links[:1000]:
            if seed in (link['source_id'], link['target_id']):
                for snapshot in json.loads(link['snapshots']):
                    if snapshot['id'] not in all_nodes:
                        all_nodes[snapshot['id']] = {**snapshot, 'current': False}
                selected.extend(key for key in (link['source_id'], link['target_id']) if key not in selected)
        tags = set(all_nodes[seed]['tags'])
        neighbors = sorted((key for key in all_nodes if key not in selected),
                           key=lambda key: (-len(tags.intersection(all_nodes[key]['tags'])), all_nodes[key]['title']))
        if include_auto:
            from .catalog_semantic import graph_candidates
            selected.extend(right for left, right, score in graph_candidates(store, seed=seed) if right not in selected)
            selected.extend(key for key in neighbors if tags.intersection(all_nodes[key]['tags']))
    else:
        for key, item in all_nodes.items():
            text = (item['title'] + ' ' + ' '.join(item['tags'])).casefold()
            if not terms or any(term and term in text for term in terms):
                selected.append(key)
    selected = list(dict.fromkeys(selected))[:limit]
    edges, counts = [], Counter()
    for link in links[:1000]:
        if link['source_id'] in selected and link['target_id'] in selected:
            edges.append({key: link[key] for key in ('id', 'revision', 'kind', 'note', 'archived')} |
                         {'source': link['source_id'], 'target': link['target_id'], 'origin': 'manual', 'label': TYPES[link['kind']]})
    if include_auto:
        pairs = []
        for index, left in enumerate(selected):
            for right in selected[index+1:]:
                common = sorted({tag for tag in all_nodes[left]['tags'] if tag.strip()} & set(all_nodes[right]['tags']))
                if common:
                    pairs.append((len(common), left, right, common))
        for _, left, right, tags in sorted(pairs, key=lambda pair: (-pair[0], pair[1], pair[2])):
            if counts[left] >= 4 or counts[right] >= 4:
                continue
            edges.append({'id': 'tag:' + str(len(edges)), 'source': left, 'target': right,
                          'origin': 'tags', 'label': '共享标签：' + '、'.join(tags[:4])})
            counts[left] += 1
            counts[right] += 1
        # Many English entries have no Zotero tags. Offer bounded, explainable
        # title clues as a separate category, never as verified research links.
        terms = {key: title_terms(all_nodes[key]['title']) for key in selected if all_nodes[key]['current']}
        frequency = Counter(term for values in terms.values() for term in values)
        weights = {term: math.log(1 + len(terms)/count) for term, count in frequency.items()
                   if count <= max(2, len(terms)*.5)}
        candidates = []
        existing = {frozenset((edge['source'], edge['target'])) for edge in edges}
        for index, left in enumerate(terms):
            for right in list(terms)[index+1:]:
                common = terms[left] & terms[right] & weights.keys()
                if not common or frozenset((left, right)) in existing:
                    continue
                total = math.sqrt(sum(weights.get(t, 0)**2 for t in terms[left]) * sum(weights.get(t, 0)**2 for t in terms[right]))
                score = sum(weights[t]**2 for t in common) / total if total else 0
                if score >= .16 and (len(common) >= 2 or any(' ' in t or t.startswith('术语:') for t in common)):
                    candidates.append((score, left, right, sorted(common, key=lambda t: (-weights[t], t))[:3]))
        inferred = Counter()
        for _, left, right, common in sorted(candidates, key=lambda pair: (-pair[0], pair[1], pair[2])):
            if inferred[left] >= 2 or inferred[right] >= 2:
                continue
            edges.append({'id': 'title:' + str(len(edges)), 'source': left, 'target': right,
                          'origin': 'title', 'label': '题名词语候选：' + '、'.join(common)})
            inferred[left] += 1
            inferred[right] += 1
        from .catalog_semantic import graph_candidates
        existing = {frozenset((edge['source'], edge['target'])) for edge in edges}
        semantic_count = Counter()
        for left, right, score in graph_candidates(store, selected=selected, limit=200):
            if (frozenset((left, right)) in existing or semantic_count[left] >= 2 or semantic_count[right] >= 2):
                continue
            edges.append({'id': 'semantic:' + str(len(edges)), 'source': left, 'target': right,
                          'origin': 'semantic', 'label': '本机书目语义邻近候选（需核对）', 'score': round(score, 5)})
            semantic_count[left] += 1
            semantic_count[right] += 1
        for board in boards:
            papers = [p['id'] for p in json.loads(board['body_json'])['papers'] if p['id'] in selected]
            for index, left in enumerate(papers):
                for right in papers[index+1:]:
                    if len(edges) < 240:
                        edges.append({'id': 'board:' + board['id'] + ':' + str(index) + ':' + right,
                                      'source': left, 'target': right, 'origin': 'comparison',
                                      'label': '同一比较表：' + board['title']})
    return {'nodes': [all_nodes[key] for key in selected], 'edges': edges, 'seed': seed,
            'total_items': len(all_items), 'limited': len(selected) == limit, 'types': TYPES,
            'links_limited': len(links) > 1000,
            'message': '共享标签、题名字词、已有书目语义索引和同一比较表提供自动线索；实线为本人建立的关系。自动连线不表示引用或结论一致。'}


def duplicates(store):
    with store.connect() as db:
        rows = db.execute("SELECT id,title,metadata FROM items WHERE kind NOT IN ('note','annotation') ORDER BY id").fetchall()
    groups = {}
    for row in rows:
        metadata = json.loads(row['metadata'])
        doi = re.sub(r'^(?:https?://(?:dx\.)?doi.org/|doi:\s*)', '', str(metadata.get('doi') or ''), flags=re.I).strip().casefold()
        title = re.sub(r'[^\w\u3400-\u9fff]', '', row['title'].casefold())
        for key in (('doi:' + doi) if doi else '', ('title:' + title) if len(title) >= 8 else ''):
            if key:
                groups.setdefault(key, []).append({'id': row['id'], 'title': row['title']})
    results, seen = [], set()
    for key, values in groups.items():
        identities = tuple(sorted(item['id'] for item in values))
        if len(values) > 1 and identities not in seen:
            seen.add(identities)
            results.append({'reason': '相同 DOI' if key.startswith('doi:') else '相同规范化题名', 'items': values[:20]})
    return {'groups': results[:40], 'total': len(results), 'message': '这些是待核对候选，不自动合并或删除；如需合并，请在 Zotero 中核对操作后再同步。'}
