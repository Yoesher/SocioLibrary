"""Create original synthetic demo documents in a NEW folder; never copy a user's library."""
import argparse
import json
from pathlib import Path

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from sociolit.crosslanguage import expand
from sociolit.indexing import import_snapshot
from sociolit.research_profiles import PROFILES
from sociolit.store import Store
from sociolit.zotero import Attachment, Snapshot


def write_pdf(path, title):
    writer = PdfWriter()
    font = writer._add_object(DictionaryObject({NameObject('/Type'): NameObject('/Font'),
        NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')}))
    for lines in ([
        'SocioLibrary - original synthetic demonstration', title,
        'This is NOT a real publication and reports no empirical findings.',
        'The document is supplied only to demonstrate local retrieval and page links.'
    ], [
        'Evidence and limitations', title,
        'No sample, interviews, experiment or data analysis was conducted.',
        'A research question is not a finding. Missing evidence must remain missing.',
        'Please use authorized research publications for an actual literature review.'
    ]):
        page = writer.add_blank_page(612, 792)
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): font})})
        stream = DecodedStreamObject()
        encoded = ['BT /F1 11 Tf 50 735 Td 20 TL']
        for line in lines:
            escaped = line.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')
            encoded.append('(' + escaped + ') Tj T*')
        stream.set_data(('\n'.join(encoded) + '\nET').encode('ascii'))
        page[NameObject('/Contents')] = writer._add_object(stream)
    writer.write(path)


def create(directory):
    directory = Path(directory).resolve()
    if directory.exists() and any(directory.iterdir()):
        raise ValueError('演示资料必须使用新的空文件夹；不会覆盖已有资料。')
    directory.mkdir(parents=True, exist_ok=True)
    papers = directory / 'demo-papers'
    papers.mkdir()
    records, attachments = [], []
    for profile in PROFILES:
        if profile['id'] == 'general':
            continue
        title = expand(profile['examples'][0])[0].title()
        path = papers / (profile['id'] + '.pdf')
        write_pdf(path, title)
        records.append(dict(key=profile['id'], title='Demo: ' + title,
            item_type='journalArticle', authors=['SocioLibrary synthetic demonstration'], year=2026,
            abstract='【原创合成演示材料，非真实论文】' + profile['examples'][0] + '。本文件仅用于演示检索和页码定位，不包含真实研究发现。',
            tags=['synthetic-demo', profile['id']]))
        attachments.append(Attachment(profile['id'] + '-pdf', profile['id'], path))
    store = Store(directory)
    result = import_snapshot(store, Snapshot('demo:social-science', records, attachments, True))
    (directory / 'preferences.json').write_text(json.dumps({'pdf_roots': [str(papers)],
        'collection_keywords': [], 'research_profile': 'general'}, ensure_ascii=False, indent=2), encoding='utf-8')
    (directory / 'DEMO-ONLY.txt').write_text('本目录全部文献为 SocioLibrary 原创合成演示材料，非真实论文，无实证研究结果。\n不含用户文献、API 密钥或私人信息。', encoding='utf-8')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Create an isolated, synthetic SocioLibrary demo library')
    parser.add_argument('--directory', required=True, type=Path)
    args = parser.parse_args()
    create(args.directory)
    print('Created 10 original synthetic documents with 20 PDF pages in an isolated directory.')
