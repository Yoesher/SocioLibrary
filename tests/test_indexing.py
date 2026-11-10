"""Real local SQLite/PDF integration checks using generated, non-private papers."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pypdf import PdfWriter
from pypdf.generic import ArrayObject, DecodedStreamObject, DictionaryObject, NameObject, NumberObject

from sociolit.indexing import extract_pdf, import_snapshot
from sociolit.store import Store
from sociolit.zotero import Attachment, Snapshot


def write_pdf(path, pages):
    writer = PdfWriter()
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                             NameObject("/Subtype"): NameObject("/Type1"),
                             NameObject("/BaseFont"): NameObject("/Helvetica")})
    font_ref = writer._add_object(font)
    for text in pages:
        page = writer.add_blank_page(width=612, height=792)
        page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_ref})})
        stream = DecodedStreamObject()
        escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream.set_data(f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET".encode("ascii"))
        page[NameObject("/Contents")] = writer._add_object(stream)
    writer._root_object[NameObject("/PageLabels")] = DictionaryObject({NameObject("/Nums"): ArrayObject([
        NumberObject(0), DictionaryObject({NameObject("/S"): NameObject("/D"), NameObject("/St"): NumberObject(41)})
    ])})
    writer.write(path)


def item(key="ABCD1234", title="劳动市场中的女性就业", kind="journalArticle", **extras):
    return {"key": key, "title": title, "item_type": kind, "authors": ["Synthetic Author"],
            "abstract": "Employment continuity and caregiving.", "tags": ["劳动"], "raw": {}, **extras}


class IndexingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.store = Store(self.directory / "library")
        self.pdf = self.directory / "synthetic.pdf"
        write_pdf(self.pdf, ["Employment is shaped by care pressure.", "Institutional protection supports labor."])

    def tearDown(self):
        self.temp.cleanup()

    def snapshot(self, source="zotero:one", records=None, attachment=True):
        return Snapshot(source, [item()] if records is None else records,
                        [Attachment("PDFD1234", "ABCD1234", self.pdf)] if attachment else [], True)

    def test_interrupted_import_retains_committed_files_and_resumes(self):
        second = self.directory / "second.pdf"
        write_pdf(second, ["Synthetic second article."])
        snapshot = Snapshot("zotero:one", [item()],
                            [Attachment("PDFD1234", "ABCD1234", self.pdf),
                             Attachment("PDFD5678", "ABCD1234", second)], True)
        def interrupt(phase, done, total):
            if phase == "pdf_index" and done == 1:
                raise RuntimeError("simulated interruption")
        with self.assertRaisesRegex(RuntimeError, "simulated interruption"):
            import_snapshot(self.store, snapshot, progress=interrupt)
        self.assertTrue(self.store.state("import_incomplete"))
        self.assertEqual(self.store.stats()["files"], 1)
        self.assertTrue(self.store.search("care pressure"))
        resumed = import_snapshot(self.store, snapshot)
        self.assertEqual(resumed["files_unchanged"], 1)
        self.assertEqual(resumed["files_indexed"], 1)
        self.assertFalse(self.store.state("import_incomplete"))

    def test_extract_actual_pdf_and_page_labels(self):
        pages = extract_pdf(self.pdf)
        self.assertEqual([(p[0], p[1]) for p in pages], [(1, "41"), (2, "42")])
        self.assertIn("care pressure", pages[0][2])
        self.assertIn("Institutional protection", pages[1][2])

    def test_search_chinese_english_and_exact_pdf_pages(self):
        stats = import_snapshot(self.store, self.snapshot())
        self.assertEqual(stats["files_indexed"], 1)
        chinese = self.store.search("女性就业")
        self.assertTrue(chinese)
        self.assertEqual(chinese[0]["kind"], "metadata")
        self.assertIsNone(chinese[0]["page"])
        english = self.store.search("institutional protection")
        self.assertEqual(len(english), 1)
        self.assertEqual(english[0]["page"], 2)
        self.assertEqual(english[0]["page_label"], "42")
        self.assertEqual(english[0]["kind"], "pdf")
        # Query punctuation cannot become FTS operators or SQL.
        self.assertEqual(self.store.search('"; DROP TABLE items; --'), [])
        self.assertEqual(self.store.stats()["items"], 1)

    def test_unchanged_snapshot_reuses_pdf_and_index(self):
        import_snapshot(self.store, self.snapshot())
        before = self.store.stats()
        with patch("sociolit.indexing.extract_pdf") as extraction:
            stats = import_snapshot(self.store, self.snapshot())
        extraction.assert_not_called()
        self.assertEqual(stats["files_unchanged"], 1)
        self.assertEqual(stats["items_changed"], 0)
        self.assertEqual(before, self.store.stats())

    def test_changed_pdf_bytes_reindex_despite_unchanged_metadata(self):
        snapshot = self.snapshot()
        snapshot.items[0]["raw"]["version"] = 0
        import_snapshot(self.store, snapshot)
        write_pdf(self.pdf, ["Replacement evidence describes occupational change."])
        stats = import_snapshot(self.store, snapshot)
        self.assertEqual(stats["items_changed"], 0)
        self.assertEqual(stats["files_indexed"], 1)
        self.assertEqual(self.store.search("institutional protection"), [])
        self.assertEqual(self.store.search("occupational change")[0]["page"], 1)

    def test_delete_prunes_only_identified_source_and_fts(self):
        import_snapshot(self.store, self.snapshot())
        import_snapshot(self.store, self.snapshot(source="zotero:two"))
        stats = import_snapshot(self.store, self.snapshot(records=[], attachment=False))
        self.assertEqual(stats["removed"], 1)
        self.assertEqual(self.store.stats()["items"], 1)
        self.assertEqual({r["source"] for r in self.store.search("care pressure")}, {"zotero:two"})
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM chunks_fts").fetchone()[0], self.store.stats()["chunks"])

    def test_incomplete_snapshot_changes_nothing(self):
        import_snapshot(self.store, self.snapshot())
        before = self.store.stats()
        old_state = self.store.state("last_import")
        with self.assertRaises(ValueError):
            import_snapshot(self.store, Snapshot("zotero:one", [], [], False))
        self.assertEqual(before, self.store.stats())
        self.assertEqual(old_state, self.store.state("last_import"))

    def test_note_results_remain_distinct_from_pdf_evidence(self):
        records = [item(), item("NOTE1234", "个人笔记", "note", raw={"note": "<p>照护责任是我的阅读假说</p>"})]
        import_snapshot(self.store, self.snapshot(records=records))
        note = self.store.search("阅读假说")[0]
        self.assertEqual(note["kind"], "note")
        self.assertIsNone(note["page"])
        self.assertIsNone(note["file_id"])
        self.assertNotIn("<p>", note["text"])

    def test_missing_pdf_clears_stale_text_and_vectors(self):
        import_snapshot(self.store, self.snapshot())
        with self.store.connect() as db:
            for row in db.execute("SELECT id FROM chunks WHERE file_id IS NOT NULL").fetchall():
                db.execute("INSERT INTO vectors VALUES(?,?,?)", (row[0], "fake-model", "[1,0]"))
        self.assertGreater(self.store.stats()["vectors"], 0)
        snapshot = self.snapshot()
        snapshot.attachments = [Attachment("PDFD1234", "ABCD1234", None, "PDF unavailable")]
        import_snapshot(self.store, snapshot)
        self.assertEqual(self.store.search("care pressure"), [])
        self.assertEqual(self.store.stats()["vectors"], 0)
        self.assertTrue(self.store.search("女性就业"))
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT status FROM files").fetchone()[0], "missing")

    def test_invalid_pdf_clears_old_evidence_and_reports_error(self):
        import_snapshot(self.store, self.snapshot())
        self.pdf.write_bytes(b"this is not a PDF")
        result = import_snapshot(self.store, self.snapshot())
        self.assertEqual(self.store.search("care pressure"), [])
        self.assertTrue(result["warnings"])
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT status FROM files").fetchone()[0], "error")

    def test_reparent_unchanged_pdf_updates_evidence_owner(self):
        records = [item(), item("NEWP1234", "新父条目")]
        import_snapshot(self.store, self.snapshot(records=records))
        snapshot = self.snapshot(records=records)
        snapshot.attachments = [Attachment("PDFD1234", "NEWP1234", self.pdf)]
        result = import_snapshot(self.store, snapshot)
        self.assertEqual(result["files_unchanged"], 1)
        self.assertEqual(self.store.search("care pressure")[0]["item_key"], "NEWP1234")

    def test_scanned_blank_pdf_flagged_for_ocr(self):
        write_pdf(self.pdf, [""])
        result = import_snapshot(self.store, self.snapshot())
        self.assertEqual(result["files_indexed"], 0)
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT status FROM files").fetchone()[0], "needs_ocr")
        self.assertTrue(result["warnings"])


if __name__ == "__main__":
    unittest.main()
