"""Safety and compatibility checks use fake Zotero responses, never a real library."""

import json
import tempfile
import unittest
from pathlib import Path

import httpx

from sociolit.zotero import ZoteroClient, ZoteroError, load_export, local_pdf_path


def article(title="劳动研究", version=0):
    return {"key": "ABCD1234", "version": version, "data": {
        "key": "ABCD1234", "itemType": "journalArticle", "title": title,
        "creators": [{"firstName": "Sample", "lastName": "Researcher"}],
        "date": "2025-01-10", "DOI": "https://doi.org/10.1234/TEST",
        "abstractNote": "社会学研究", "tags": [{"tag": "劳动"}],
    }}


def pdf_item():
    return {"key": "PDFD1234", "data": {
        "key": "PDFD1234", "itemType": "attachment", "parentItem": "ABCD1234",
        "contentType": "application/pdf", "filename": "研究 测试.pdf",
    }}


class ZoteroTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.pdf = self.root / "研究 测试.pdf"
        self.pdf.write_bytes(b"%PDF-1.4\n% synthetic test file\n")

    def tearDown(self):
        self.temp.cleanup()

    def client(self, handler, **kwargs):
        return ZoteroClient(transport=httpx.MockTransport(handler), **kwargs)

    def test_complete_snapshot_and_local_pdf(self):
        requested = []

        def handler(request):
            requested.append(request)
            self.assertEqual(request.method, "GET")
            self.assertEqual(request.url.host, "127.0.0.1")
            self.assertNotIn("zotero-api-key", request.headers)
            if request.url.path.endswith("/items"):
                self.assertNotIn("since", request.url.params)
                return httpx.Response(200, json=[article(), pdf_item()], headers={
                    "Zotero-Server-ID": "instance-one", "Total-Results": "2",
                })
            self.assertEqual(request.headers["Zotero-Server-ID"], "instance-one")
            self.assertTrue(request.url.path.endswith("/PDFD1234/file/view/url"))
            return httpx.Response(200, text=self.pdf.as_uri(), headers={"Zotero-Server-ID": "instance-one"})

        with self.client(handler, allowed_roots=[self.root]) as client:
            snapshot = client.snapshot()
        self.assertTrue(snapshot.complete)
        self.assertEqual(snapshot.source_id, "zotero:instance-one")
        self.assertEqual(snapshot.items[0]["authors"], ["Sample Researcher"])
        self.assertEqual(snapshot.items[0]["doi"], "10.1234/test")
        self.assertEqual(snapshot.items[0]["year"], 2025)
        self.assertEqual(snapshot.attachments[0].path, self.pdf.resolve())
        self.assertEqual(len(requested), 2)

    def test_zero_version_local_edit_still_returned(self):
        titles = iter(["旧标题", "本地修订标题"])
        def handler(request):
            self.assertNotIn("since", request.url.params)
            return httpx.Response(200, json=[article(next(titles), version=0)])
        with self.client(handler) as client:
            first = client.snapshot()
            second = client.snapshot()
        self.assertEqual(first.source_id, second.source_id)
        self.assertNotEqual(first.items[0]["title"], second.items[0]["title"])

    def test_empty_roots_import_metadata_and_warn(self):
        def handler(request):
            if request.url.path.endswith("/items"):
                return httpx.Response(200, json=[article(), pdf_item()])
            return httpx.Response(200, text=self.pdf.as_uri())
        with self.client(handler) as client:
            result = client.snapshot()
        self.assertEqual(len(result.items), 1)
        self.assertIsNone(result.attachments[0].path)
        self.assertIn("授权", result.attachments[0].warning)

    def test_rejects_nonlocal_api_addresses(self):
        bad = ["https://api.zotero.org/api", "http://evil.example/api",
               "http://127.0.0.1.evil.example/api", "http://127.0.0.1:23119/connector",
               "http://user:secret@127.0.0.1:23119/api", "http://127.0.0.1:23119/api?key=secret"]
        for address in bad:
            with self.subTest(address=address), self.assertRaises(ZoteroError):
                ZoteroClient(address)

    def test_localhost_canonicalized(self):
        def handler(request):
            self.assertEqual(request.url.host, "127.0.0.1")
            return httpx.Response(200, json=[])
        with self.client(handler, base_url="http://localhost:23119/api/") as client:
            self.assertTrue(client.snapshot().complete)

    def test_http_redirect_never_followed(self):
        calls = []
        def handler(request):
            calls.append(request)
            return httpx.Response(302, headers={"Location": "https://evil.example/"})
        with self.client(handler) as client, self.assertRaises(ZoteroError):
            client.snapshot()
        self.assertEqual(len(calls), 1)

    def test_malformed_or_partial_snapshot_fails(self):
        cases = [(200, {"wrong": True}, {}),
                 (200, [article()], {"Total-Results": "2"}),
                 (200, [article()], {"Link": '<http://127.0.0.1:23119/api/users/0/items?start=1>; rel="next"'}),
                 (200, [article(), article()], {}),
                 (403, {}, {}), (500, {}, {})]
        for status, body, headers in cases:
            with self.subTest(status=status, headers=headers):
                with self.client(lambda _, status=status, body=body, headers=headers: httpx.Response(status, json=body, headers=headers)) as client:
                    with self.assertRaises(ZoteroError):
                        client.snapshot()

    def test_missing_pdf_retains_metadata(self):
        def handler(request):
            if request.url.path.endswith("/items"):
                return httpx.Response(200, json=[article(), pdf_item()])
            return httpx.Response(404)
        with self.client(handler) as client:
            snapshot = client.snapshot()
        self.assertTrue(snapshot.complete)
        self.assertEqual(len(snapshot.items), 1)
        self.assertIsNone(snapshot.attachments[0].path)

    def test_database_switch_mid_read_fails(self):
        def handler(request):
            if request.url.path.endswith("/items"):
                return httpx.Response(200, json=[article(), pdf_item()], headers={"Zotero-Server-ID": "one"})
            return httpx.Response(412)
        with self.client(handler) as client, self.assertRaises(ZoteroError):
            client.snapshot()

    def test_server_identity_changes_source(self):
        ids = iter(["one", "two"])
        with self.client(lambda _: httpx.Response(200, json=[], headers={"Zotero-Server-ID": next(ids)})) as client:
            self.assertNotEqual(client.snapshot().source_id, client.snapshot().source_id)

    def test_notes_are_distinct_and_deleted_excluded(self):
        note = {"key": "NOTE1234", "data": {"itemType": "note", "note": "<p>个人理解</p>"}}
        deleted = article()
        deleted["data"]["deleted"] = 1
        with self.client(lambda _: httpx.Response(200, json=[note, deleted])) as client:
            result = client.snapshot()
        self.assertEqual(len(result.items), 1)
        self.assertEqual(result.items[0]["item_type"], "note")

    def test_local_path_allowlist(self):
        self.assertEqual(local_pdf_path(self.pdf.as_uri(), [self.root]), self.pdf.resolve())
        for value in ["file://server/share/a.pdf", "https://example.org/a.pdf",
                      "\\\\server\\share\\a.pdf", "//server/share/a.pdf", "relative.pdf",
                      self.pdf.as_uri() + "?x=1"]:
            with self.subTest(value=value), self.assertRaises(ZoteroError):
                local_pdf_path(value, [self.root])
        with self.assertRaises(ZoteroError):
            local_pdf_path(self.pdf.as_uri(), [self.root / "different"])
        with self.assertRaises(ZoteroError):
            local_pdf_path(str(self.root / "missing.pdf"), [self.root])

    def test_symlink_escape_rejected(self):
        with tempfile.TemporaryDirectory() as other:
            outside = Path(other) / "outside.pdf"
            outside.write_bytes(b"%PDF-1.4")
            link = self.root / "linked.pdf"
            try:
                link.symlink_to(outside)
            except OSError:
                self.skipTest("Host does not permit symlinks")
            with self.assertRaises(ZoteroError):
                local_pdf_path(str(link), [self.root])

    def test_csl_export_metadata(self):
        path = self.root / "export.json"
        path.write_text(json.dumps([{"id": "csl-one", "type": "article-journal", "title": "劳动",
                                    "author": [{"family": "何", "given": "国希"}],
                                    "issued": {"date-parts": [[2024]]}}]), encoding="utf-8")
        result = load_export(path)
        self.assertEqual(result.items[0]["year"], 2024)
        self.assertEqual(result.items[0]["authors"], ["国希 何"])
        self.assertEqual(result.attachments, [])

    def test_native_json_relative_pdf_and_stable_source(self):
        path = self.root / "export.json"
        data = article()["data"]
        data["attachments"] = [{"key": "PDFD1234", "path": self.pdf.name}]
        path.write_text(json.dumps({"items": [data]}), encoding="utf-8")
        first = load_export(path, [self.root])
        data["title"] = "修改标题"
        path.write_text(json.dumps({"items": [data]}), encoding="utf-8")
        second = load_export(path, [self.root])
        self.assertEqual(first.source_id, second.source_id)
        self.assertEqual(first.items[0]["key"], second.items[0]["key"])
        self.assertEqual(first.attachments[0].path, self.pdf.resolve())

    def test_export_cannot_escape_root(self):
        path = self.root / "export.json"
        path.write_text(json.dumps({"items": [{"key": "ABCD1234", "title": "Test",
                           "attachments": [{"path": "https://evil.example/private.pdf"}]}]}), encoding="utf-8")
        result = load_export(path, [self.root])
        self.assertIsNone(result.attachments[0].path)
        self.assertTrue(result.warnings)


if __name__ == "__main__":
    unittest.main()
