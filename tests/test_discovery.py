import gzip
import json
import socket
from datetime import date

import httpx
import pytest

from sociolit.discovery import (
    DiscoveryError,
    DiscoveryResult,
    canonicalize_doi,
    merge_records,
    persist_discovery,
    run_discovery,
)

SINCE, UNTIL = date(2026, 9, 1), date(2026, 11, 6)
SUB = {"name": "Synthetic Journal", "issns": ["1234-5678"], "enabled": True, "sources": ["crossref"]}


def record(doi="10.1234/test", title="Employment and Care", **kwargs):
    return {"title": title, "doi": doi, "authors": ["Researcher A"], "year": "2026",
            "published_date": "2026-10-01", "sources": ["crossref"], **kwargs}


def run(handler, subscriptions=None, **kwargs):
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        return run_discovery(subscriptions or [SUB], SINCE, UNTIL, client=client, sleep=lambda _: None, **kwargs)


@pytest.mark.parametrize("value", ["10.1234/TEST", "doi: 10.1234/Test", "https://DOI.org/10.1234%2FTest"])
def test_doi_canonicalization(value):
    assert canonicalize_doi(value) == "10.1234/test"


def test_dedup_merges_aliases_and_never_different_dois():
    records = merge_records([record(), record("https://doi.org/10.1234/TEST", sources=["openalex"]), record("10.1234/other")])
    assert len(records) == 2
    assert next(r for r in records if r["doi"] == "10.1234/test")["sources"] == ["crossref", "openalex"]
    assert len(merge_records([record(""), record()])) == 1


def test_ambiguous_title_matches_are_not_merged():
    assert len(merge_records([record(), record("10.1234/other"), record("")])) == 3


def test_crossref_cursor_and_index_dates():
    calls = []
    def handler(request):
        calls.append(request)
        assert request.url.params["filter"] == "from-index-date:2026-09-01,until-index-date:2026-11-06"
        assert request.url.params["rows"] == "100"
        if len(calls) == 1:
            return httpx.Response(200, json={"message": {"items": [{"DOI": f"10.1234/{i}", "title": [f"Title {i}"]} for i in range(100)], "next-cursor": "page2"}})
        assert request.url.params["cursor"] == "page2"
        return httpx.Response(200, json={"message": {"items": [{"DOI": "10.1234/end", "title": ["Final title"], "author": [{"given": "A", "family": "Person"}], "issued": {"date-parts": [[2026, 10]]}}]}})
    result = run(handler)
    assert result.complete and len(result.records) == 101
    assert next(r for r in result.records if r["doi"] == "10.1234/end")["published_date"] == "2026-10"


def test_compressed_api_response_is_decoded_only_once():
    body = gzip.compress(json.dumps({"message": {"items": [{"DOI": "10.1234/gzip", "title": ["Compressed metadata"]}]}}).encode())
    result = run(lambda request: httpx.Response(200, headers={"Content-Encoding": "gzip"}, content=body))
    assert result.complete and result.records[0]["doi"] == "10.1234/gzip"


def test_page_limit_is_a_visible_failure():
    result = run(lambda r: httpx.Response(200, json={"message": {"items": [{"title": [str(i)], "DOI": f"10.1234/{i}"} for i in range(100)], "next-cursor": "more"}}), max_pages=1)
    assert not result.complete
    assert "page limit" in result.errors[0]


def test_retries_and_retry_after():
    calls, sleeps = [], []
    def handler(request):
        calls.append(request)
        return httpx.Response(429, headers={"Retry-After": "2"}) if len(calls) == 1 else httpx.Response(200, json={"message": {"items": []}})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = run_discovery([SUB], SINCE, UNTIL, client=client, sleep=sleeps.append)
    assert result.complete and len(calls) == 2 and 2 in sleeps


def test_long_retry_is_deferred_not_slept():
    result = run(lambda r: httpx.Response(429, headers={"Retry-After": "3600"}))
    assert not result.complete and "long wait" in result.errors[0]


def test_source_failure_does_not_hide_other_source(monkeypatch):
    monkeypatch.delenv("OPENALEX_API_KEY", raising=False)
    result = run(lambda r: httpx.Response(200, json={"message": {"items": [{"DOI": "10.1234/one", "title": ["Kept"]}]}}), [{**SUB, "sources": ["openalex", "crossref"]}])
    assert len(result.records) == 1 and not result.complete
    assert "OPENALEX_API_KEY" in result.errors[0]


def test_openalex_bearer_and_supported_page_size(monkeypatch):
    monkeypatch.setenv("OPENALEX_API_KEY", "private-test-value")
    calls = []
    def handler(request):
        calls.append(request)
        assert request.headers["Authorization"] == "Bearer private-test-value"
        assert "private-test-value" not in str(request.url)
        assert request.url.params["per_page"] == "100"
        assert "from_publication_date" in request.url.params["filter"]
        assert "from_updated_date" not in request.url.params["filter"]
        if len(calls) == 1:
            return httpx.Response(200, json={"meta": {"next_cursor": "second"}, "results": [{"id": "https://openalex.org/W1", "title": "Article", "doi": "https://doi.org/10.1234/one", "publication_date": "2026-10-01", "primary_location": None}]})
        assert request.url.params["cursor"] == "second"
        return httpx.Response(200, json={"meta": {"next_cursor": None}, "results": []})
    result = run(handler, [{**SUB, "sources": ["openalex"]}])
    assert result.complete and len(calls) == 2 and len(result.records) == 1


def test_network_error_never_logs_key(monkeypatch):
    monkeypatch.setenv("OPENALEX_API_KEY", "private-test-value")
    def handler(request):
        raise httpx.ConnectError("private-test-value", request=request)
    result = run(handler, [{**SUB, "sources": ["openalex"]}])
    assert not result.complete and "private-test-value" not in str(result.errors)


def public_dns(*args, **kwargs):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]


def test_rss_atom_dates_and_relative_links(monkeypatch):
    monkeypatch.setattr("sociolit.discovery.socket.getaddrinfo", public_dns)
    feed = b'''<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Care &amp; Work</title><id>tag:one</id><author><name>Writer</name></author><published>2026-10-01T10:00:00Z</published><link href="/article/1" /></entry><entry><title>Old</title><published>2020-01-01</published></entry></feed>'''
    result = run(lambda r: httpx.Response(200, content=feed), [{**SUB, "sources": ["rss"], "rss_url": "https://example.org/feed"}])
    assert result.complete and len(result.records) == 1
    assert result.records[0]["url"] == "https://example.org/article/1"
    assert result.records[0]["authors"] == ["Writer"]


def test_rss_xml_entity_rejected(monkeypatch):
    monkeypatch.setattr("sociolit.discovery.socket.getaddrinfo", public_dns)
    feed = b'<!DOCTYPE rss [<!ENTITY secret SYSTEM "file:///etc/passwd">]><rss><channel><item><title>&secret;</title></item></channel></rss>'
    result = run(lambda r: httpx.Response(200, content=feed), [{**SUB, "sources": ["rss"], "rss_url": "https://example.org/feed"}])
    assert not result.complete and "unsafe XML" in result.errors[0]


def test_rss_html_error_page_is_not_empty_success(monkeypatch):
    monkeypatch.setattr("sociolit.discovery.socket.getaddrinfo", public_dns)
    result = run(lambda r: httpx.Response(200, content=b"<html><body>HTTP404</body></html>"), [{**SUB, "sources": ["rss"], "rss_url": "https://example.org/feed"}])
    assert not result.complete and "not an RSS/Atom feed" in result.errors[0]


def test_rss_redirect_to_loopback_rejected(monkeypatch):
    def dns(host, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1" if host == "localhost" else "93.184.216.34", 443))]
    monkeypatch.setattr("sociolit.discovery.socket.getaddrinfo", dns)
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(302, headers={"Location": "https://localhost/private"})
    result = run(handler, [{**SUB, "sources": ["rss"], "rss_url": "https://example.org/feed"}])
    assert not result.complete and len(calls) == 1


def test_disabled_subscriptions_make_no_requests():
    def handler(request):
        pytest.fail("disabled subscription must make no network request")
    assert run(handler, [{**SUB, "enabled": False}]).complete


def test_persistent_cache_is_idempotent_and_allowlisted(tmp_path):
    result = DiscoveryResult(records=[record(abstract="Private abstract", pdf_path="C:/private/paper.pdf", api_key="secret")])
    first = persist_discovery(result, tmp_path / "state", output_dir=tmp_path / "out")
    second = persist_discovery(result, tmp_path / "state", output_dir=tmp_path / "out")
    assert first["new"] == 1 and second["new"] == second["updated"] == 0
    assert first["digest_path"].endswith("digest.md") and first["metadata_path"].endswith("records.json")
    stored = (tmp_path / "state/metadata-cache.json").read_text(encoding="utf-8")
    assert "Private abstract" not in stored and "paper.pdf" not in stored and "secret" not in stored
    assert len(json.loads(stored)["records"]) == 1
    assert len(list((tmp_path / "state/history").glob("*.md"))) == 2
    assert len(list((tmp_path / "state/history").glob("*.json"))) == 2


def test_doi_enrichment_is_an_update(tmp_path):
    persist_discovery(DiscoveryResult(records=[record("")]), tmp_path)
    stats = persist_discovery(DiscoveryResult(records=[record()]), tmp_path)
    assert stats["new"] == 0 and stats["updated"] == 1 and stats["total"] == 1


def test_same_doi_refresh_updates_title_year_and_authors(tmp_path):
    persist_discovery(DiscoveryResult(records=[record(title="Old title", year="2025")]), tmp_path)
    current = DiscoveryResult(records=[record(title="Corrected title", year="2026", authors=["Corrected Author"], published_date="2026-11-01")])
    stats = persist_discovery(current, tmp_path)
    assert stats["new"] == 0 and stats["updated"] == 1 and stats["total"] == 1
    saved = json.loads((tmp_path / "metadata-cache.json").read_text(encoding="utf-8"))["records"]
    assert saved[0]["title"] == "Corrected title" and saved[0]["year"] == "2026"
    assert saved[0]["authors"] == ["Corrected Author"]
    assert persist_discovery(current, tmp_path)["updated"] == 0


def test_corrupt_cache_preserved(tmp_path):
    path = tmp_path / "metadata-cache.json"
    path.write_text("not valid", encoding="utf-8")
    with pytest.raises(DiscoveryError, match="cache is invalid"):
        persist_discovery(DiscoveryResult(), tmp_path)
    assert path.read_text() == "not valid"
