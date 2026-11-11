"""Build a Zotero deep link only from an indexed local attachment and page.

The current importer reads /users/0 only. Group libraries require an explicit
group mapping before they can use this protocol (never guess a group ID).
"""
import re
from urllib.parse import quote


def locate(store, file_id, page):
    if not isinstance(file_id, str) or len(file_id) > 1000 or type(page) is not int or not 1 <= page <= 3000:
        raise ValueError('原文定位无效，请重新检索。')
    with store.connect() as db:
        row = db.execute('''SELECT f.id,f.status,i.source FROM files f
            JOIN items i ON i.id=f.item_id WHERE f.id=?''', (file_id,)).fetchone()
        found = db.execute('SELECT 1 FROM chunks WHERE file_id=? AND page=? LIMIT 1', (file_id, page)).fetchone()
    if not row or not found or row['status'] not in ('indexed', 'needs_ocr'):
        raise ValueError('该原文页已不可用，请同步 Zotero 后重试。')
    uri = None
    source = row['source']
    key = file_id.removeprefix(source + ':')
    if source.startswith('zotero:') and file_id.startswith(source + ':') and re.fullmatch(r'[A-Z0-9]{8}', key):
        uri = f'zotero://open-pdf/library/items/{key}?page={page}'
    return {'zotero_url': uri, 'pdf_url': '/api/pdf/' + quote(file_id, safe='') + '#page=' + str(page),
            'file_id': file_id, 'page': page}
