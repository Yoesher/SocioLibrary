"""Persistent, server-verified research maps and portable knowledge packages."""
import io
import json
import math
import re
import uuid
import zipfile
from datetime import datetime, timezone
from hashlib import sha256
from html import escape
from urllib.parse import quote

from . import graph
from .discovery import canonicalize_doi


def initialize(store):
    with store.connect() as db:
        db.execute('''CREATE TABLE IF NOT EXISTS graph_views (
            id TEXT PRIMARY KEY,name TEXT NOT NULL,state_json TEXT NOT NULL,data_json TEXT NOT NULL,
            revision TEXT NOT NULL,updated TEXT NOT NULL,archived INTEGER NOT NULL DEFAULT 0)''')


def _number(value, low, high):
    if type(value) not in (float, int) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError('图谱位置或缩放无效，请重新保存。')
    return value


def save(store, name, state):
    name = name.strip()
    ids = state.get('ids', [])
    if not name or len(name) > 80 or any(ord(c) < 32 for c in name):
        raise ValueError('视图名称应为1至80字。')
    if (not isinstance(ids, list) or not 1 <= len(ids) <= 80
            or any(not isinstance(key, str) or not 1 <= len(key) <= 1000 for key in ids)):
        raise ValueError('视图最多80篇文献。')
    layout, origin = state.get('layout', 'network'), state.get('origin', 'all')
    if layout not in ('network', 'concentric', 'timeline') or origin not in ('all', 'manual', 'words', 'semantic', 'comparison'):
        raise ValueError('无效的布局或关系来源。')
    positions = state.get('positions', {})
    if not isinstance(positions, dict) or any(not isinstance(v, dict) for v in positions.values()) or set(positions) != set(ids):
        raise ValueError('文献与位置不一致，请重新保存。')
    positions = {key: {axis: _number(positions[key].get(axis), -1e6, 1e6) for axis in ('x', 'y')} for key in ids}
    viewport = state.get('viewport', {})
    if not isinstance(viewport, dict) or not isinstance(viewport.get('pan'), dict):
        raise ValueError('图谱视角无效。')
    pan = viewport.get('pan', {})
    viewport = {'zoom': _number(viewport.get('zoom'), .12, 2.7),
                'pan': {axis: _number(pan.get(axis), -1e6, 1e6) for axis in ('x', 'y')}}
    pinned = state.get('pinned', [])
    if not isinstance(pinned, list) or any(key not in ids for key in pinned) or len(pinned) > 80:
        raise ValueError('固定位置包含无效文献。')
    # Never persist client-supplied titles, edges, citation claims, paths or URLs.
    data = graph.build(store, selected_ids=ids, limit=80,
                       include_auto=bool(state.get('auto', True)), include_archived=bool(state.get('archived', False)))
    clean = {'ids': ids, 'positions': positions, 'viewport': viewport, 'pinned': list(dict.fromkeys(pinned)),
             'layout': layout, 'origin': origin, 'seed': state.get('seed') if state.get('seed') in ids else '',
             'selected': state.get('selected') if state.get('selected') in ids else '',
             'query': str(state.get('query', ''))[:200], 'limit': str(min(80, max(15, len(ids)))),
             'auto': bool(state.get('auto', True)), 'archived': bool(state.get('archived', False)),
             'orphans': bool(state.get('orphans', True)), 'node_scale': _number(state.get('node_scale', 100), 70, 160),
             'label_mode': 'all' if state.get('label_mode') == 'all' else 'adaptive'}
    identity, revision, updated = uuid.uuid4().hex, uuid.uuid4().hex, datetime.now(timezone.utc).isoformat()
    with store.connect() as db:
        if db.execute('SELECT count(*) FROM graph_views WHERE archived=0').fetchone()[0] >= 100:
            raise ValueError('最多保存100个活动视图，请先归档旧视图。')
        db.execute('INSERT INTO graph_views VALUES(?,?,?,?,?,?,0)',
                   (identity, name, json.dumps(clean, ensure_ascii=False), json.dumps(data, ensure_ascii=False), revision, updated))
    return {'id': identity, 'revision': revision, 'name': name}


def listing(store, archived=False):
    with store.connect() as db:
        return [dict(row) for row in db.execute('''SELECT id,name,revision,updated,archived,
            json_array_length(state_json,'$.ids') AS count FROM graph_views
            WHERE archived=? ORDER BY updated DESC LIMIT 100''', (int(archived),))]


def get(store, identity):
    with store.connect() as db:
        row = db.execute('SELECT * FROM graph_views WHERE id=?', (identity,)).fetchone()
        if not row:
            raise ValueError('保存的图谱不存在。')
        current = {r[0] for r in db.execute('SELECT id FROM items')}
    result = dict(row)
    result['state'], result['data'] = json.loads(result.pop('state_json')), json.loads(result.pop('data_json'))
    for node in result['data']['nodes']:
        node['current'] = node['id'] in current
    for edge in result['data']['edges']:
        edge['snapshot'] = True
    return result


def archive(store, identity, revision, archived):
    with store.connect() as db:
        cursor = db.execute('UPDATE graph_views SET archived=?,revision=? WHERE id=? AND revision=?',
                            (int(archived), uuid.uuid4().hex, identity, revision))
        if not cursor.rowcount:
            raise ValueError('保存视图已变化，请刷新列表。')
    return {'saved': True}


def _md(value):
    return re.sub(r'([\\`*_{}\[\]()#!|>])', r'\\\1', escape(str(value), quote=False))


def _zotero(identity):
    match = re.fullmatch(r'zotero:[^:]+:([A-Z0-9]{8})', identity)
    return 'zotero://select/library/items/' + match[1] if match else ''


def export(store, identity, include_annotations=False):
    view = get(store, identity)
    nodes, edges, notes, occupied = [], [], {}, []
    mapping = {n['id']: uuid.uuid4().hex[:16] for n in view['data']['nodes']}
    for node in view['data']['nodes']:
        key = node['id']
        stem = 'paper-' + sha256(key.encode()).hexdigest()[:20]
        path = 'notes/' + stem + '.md'
        with store.connect() as db:
            row = db.execute('SELECT metadata FROM items WHERE id=?', (key,)).fetchone()
            annotations = db.execute('SELECT data_json,file_id,current FROM zotero_annotations WHERE item_id=? ORDER BY id LIMIT 20', (key,)).fetchall() if include_annotations else []
        meta = json.loads(row[0]) if row else {}
        link, doi = _zotero(key), canonicalize_doi(node.get('doi'))
        lines = ['# ' + _md(node['title']), '', ' · '.join(_md(v) for v in [*node.get('authors', []), node.get('year', '')] if v), '',
                 '此笔记与画布来自保存时的研究图谱；关系为历史线索快照。', '']
        if not node['current']:
            lines += ['原条目已移出当前资料库；保留保存时书目信息。', '']
        if link:
            lines += [f'[在 Zotero 中定位文献]({link})', '']
        if doi:
            lines += [f'[DOI](https://doi.org/{quote(doi, safe="/")})', '']
        abstract = str(meta.get('abstract') or '')[:6000]
        lines += ['## 来源摘要', '', _md(abstract) if abstract else '未取得来源摘要。', '']
        lines += ['## 关联线索', '']
        for edge in view['data']['edges']:
            if key not in (edge['source'], edge['target']):
                continue
            other = edge['target'] if edge['source'] == key else edge['source']
            target = 'paper-' + sha256(other.encode()).hexdigest()[:20] + '.md'
            lines += [f'- [{_md(edge["label"])}]({target})（保存时线索；{_md(edge["origin"])}）']
        for annotation in annotations:
            a = json.loads(annotation['data_json'])
            lines += ['', '## Zotero 批注快照' + ('' if annotation['current'] else '（原批注已移除）'), '']
            if a.get('text'):
                lines += ['摘录：' + _md(a['text'][:4000])]
            if a.get('comment'):
                lines += ['个人评论（不是作者原文）：' + _md(a['comment'][:4000])]
            page, attachment = a.get('page'), annotation['file_id']
            match = re.fullmatch(r'zotero:[^:]+:([A-Z0-9]{8})', attachment)
            if match and type(page) is int and 1 <= page <= 3000:
                lines += [f'[PDF 第 {page} 页](zotero://open-pdf/library/items/{match[1]}?page={page})']
        notes[path] = '\n'.join(lines) + '\n'
        p = view['state']['positions'][key]
        x, y = round(p['x']*3), round(p['y']*3)
        while any(abs(x-a) < 360 and abs(y-b) < 230 for a, b in occupied):
            y += 250
        occupied.append((x, y))
        nodes.append({'id': mapping[key], 'type': 'file', 'file': path, 'x': x, 'y': y, 'width': 330, 'height': 200})
    for edge in view['data']['edges']:
        edges.append({'id': uuid.uuid4().hex[:16], 'fromNode': mapping[edge['source']], 'toNode': mapping[edge['target']],
                      'fromEnd': 'none', 'toEnd': 'arrow' if edge.get('kind') == 'cites' else 'none',
                      'label': edge['label'] + '（保存时线索）'})
    notes['SocioLibrary.canvas'] = json.dumps({'nodes': nodes, 'edges': edges}, ensure_ascii=False, indent=2)
    notes['README.md'] = '# SocioLibrary 研究包\n\n解压后，将整个文件夹放入 Obsidian 文库并打开 SocioLibrary.canvas。notes 内的文献笔记可独立阅读。没有附带 PDF、密钥或本机绝对路径。\n\n摘要、可选批注和关系均为导出快照；自动线索不表示实际引文或结论一致。当前版本每篇最多导出20条批注，每条摘录/评论最多4000字，来源摘要最多6000字。\n'
    if sum(len(v.encode()) for v in notes.values()) > 20_000_000:
        raise ValueError('研究包超过20 MB，请缩小图谱或取消附带批注。')
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive_file:
        for path, text in notes.items():
            archive_file.writestr(path, text)
    return output.getvalue()
