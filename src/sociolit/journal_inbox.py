"""A paged local inbox, independent of publisher metadata refreshes."""
import json
from datetime import datetime, timezone
from hashlib import sha256

from .discovery import _public_link

SOURCE = 'journals:public-metadata'


def initialize(store):
    with store.connect() as db:
        db.execute('''CREATE TABLE IF NOT EXISTS journal_inbox (
            item_id TEXT PRIMARY KEY,fingerprint TEXT NOT NULL,first_seen TEXT NOT NULL,
            changed TEXT NOT NULL,read INTEGER NOT NULL DEFAULT 0,
            favorite INTEGER NOT NULL DEFAULT 0,updated_record INTEGER NOT NULL DEFAULT 0)''')


def sync(store):
    initialize(store)
    now = datetime.now(timezone.utc).isoformat()
    with store.connect() as db:
        for row in db.execute('SELECT id,title,metadata FROM items WHERE source=?', (SOURCE,)).fetchall():
            fingerprint = sha256((row['title'] + json.dumps(json.loads(row['metadata']), sort_keys=True)).encode()).hexdigest()
            db.execute('''INSERT INTO journal_inbox(item_id,fingerprint,first_seen,changed) VALUES(?,?,?,?)
                ON CONFLICT(item_id) DO UPDATE SET fingerprint=excluded.fingerprint,changed=excluded.changed,
                read=0,updated_record=1 WHERE journal_inbox.fingerprint<>excluded.fingerprint''',
                       (row['id'], fingerprint, now, now))


def listing(store, query='', journal='', state='unread', offset=0, limit=20):
    if state not in ('unread', 'all', 'favorites') or not 0 <= offset <= 100000 or not 1 <= limit <= 50:
        raise ValueError('期刊筛选条件或页码无效。')
    query = query.strip().casefold()
    if len(query) > 200 or len(journal) > 100:
        raise ValueError('期刊检索内容过长。')
    pattern = '%' + query.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
    where = '''i.source=? AND (?='' OR lower(i.title||' '||i.metadata) LIKE ? ESCAPE '\\')
        AND (?='' OR json_extract(i.metadata,'$.raw.journal')=?)
        AND (?<>'unread' OR b.read=0) AND (?<>'favorites' OR b.favorite=1)'''
    args = (SOURCE, query, pattern, journal, journal, state, state)
    with store.connect() as db:
        total = db.execute('SELECT count(*) FROM journal_inbox b JOIN items i ON i.id=b.item_id WHERE '+where, args).fetchone()[0]
        rows = db.execute('''SELECT b.*,i.title,i.metadata FROM journal_inbox b JOIN items i ON i.id=b.item_id WHERE ''' + where +
                          ' ORDER BY b.changed DESC,i.id LIMIT ? OFFSET ?', (*args, limit, offset)).fetchall()
        journals = [r[0] for r in db.execute("SELECT DISTINCT json_extract(metadata,'$.raw.journal') FROM items WHERE source=? ORDER BY 1", (SOURCE,)) if r[0]]
        unread = db.execute('SELECT count(*) FROM journal_inbox b JOIN items i ON i.id=b.item_id WHERE i.source=? AND b.read=0', (SOURCE,)).fetchone()[0]
    records = []
    for row in rows:
        meta = json.loads(row['metadata'])
        raw = meta.get('raw') or {}
        records.append({'item_id': row['item_id'], 'title': row['title'], 'authors': meta.get('authors', []),
                        'year': meta.get('year', ''), 'journal': raw.get('journal', ''), 'doi': meta.get('doi', ''),
                        'url': _public_link(raw.get('url')), 'published_date': raw.get('published_date', ''),
                        'sources': raw.get('sources', []), 'first_seen': row['first_seen'], 'changed': row['changed'],
                        'read': bool(row['read']), 'favorite': bool(row['favorite']), 'updated_record': bool(row['updated_record'])})
    return {'records': records, 'total': total, 'unread': unread, 'journals': journals, 'offset': offset, 'limit': limit}


def mark(store, identity, read=None, favorite=None):
    with store.connect() as db:
        if not db.execute('SELECT 1 FROM journal_inbox b JOIN items i ON i.id=b.item_id WHERE b.item_id=? AND i.source=?', (identity, SOURCE)).fetchone():
            raise ValueError('该条期刊动态不在当前收件箱。')
        for key, value in (('read', read), ('favorite', favorite)):
            if value is not None:
                db.execute('UPDATE journal_inbox SET '+key+'=? WHERE item_id=?', (int(value), identity))
    return {'saved': True}
