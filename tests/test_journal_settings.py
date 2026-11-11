from copy import deepcopy

import httpx
import pytest
from fastapi.testclient import TestClient

from sociolit.discovery import DiscoveryError, DiscoveryResult
from sociolit.server import create_app
from sociolit.store import Store
from sociolit.subscriptions import (
    apply_feeds,
    configure_journal,
    probe_journal,
    subscription_views,
    toggle_journal,
)


def defaults():
    return {"journals": [{"name": "Built-in", "enabled": True, "sources": ["official_toc"],
                           "homepage": "https://publisher.example/"},
                          {"name": "Pending", "enabled": False, "sources": []}]}


def identity(provider, issns):
    assert provider == "crossref" and issns == ["0003-1224"]
    return "American Sociological Review"


def test_custom_journal_survives_restart_and_pausing_preserves_library(tmp_path):
    store, config = Store(tmp_path), defaults()
    counts = store.stats()
    configure_journal(store, config, "ASR", "crossref", issns=["00031224"], probe=identity)
    restarted = defaults()
    apply_feeds(Store(tmp_path), restarted)
    journal = subscription_views(restarted)[-1]
    assert journal["source_title"] == "American Sociological Review" and journal["enabled"]
    toggle_journal(store, restarted, "ASR", False)
    assert not restarted["journals"][-1]["enabled"]
    toggle_journal(store, restarted, "ASR", True)
    assert restarted["journals"][-1]["enabled"] and store.stats() == counts
    assert config["_journal_defaults"] == defaults()["journals"]


def test_invalid_replacement_never_changes_saved_subscription(tmp_path):
    store, config = Store(tmp_path), defaults()
    configure_journal(store, config, "ASR", "crossref", issns=["0003-1224"], probe=identity)
    before = deepcopy(store.state("journal-subscriptions"))
    for invalid in ([], ["0003-1225"], ["../secret"]):
        with pytest.raises(ValueError):
            configure_journal(store, config, "ASR", "crossref", issns=invalid, probe=identity)
    def fail(*args):
        raise DiscoveryError("HTTP 404")
    with pytest.raises(ValueError):
        configure_journal(store, config, "ASR", "crossref", issns=["0003-1224"], probe=fail)
    with pytest.raises(ValueError):
        configure_journal(store, config, "ASR", "rss", url="https://publisher.example/feed",
                          runner=lambda *a: DiscoveryResult(errors=["wrong channel"]))
    assert store.state("journal-subscriptions") == before


def test_custom_rss_requires_public_settings_and_verified_channel(tmp_path):
    store, config = Store(tmp_path), defaults()
    calls = []
    def feed(journals, *args):
        calls.append(journals)
        assert journals[0]["required_feed_title"] == "English Journal"
        return DiscoveryResult()
    for url in ("http://publisher.example/feed", "https://user:pass@publisher.example/feed",
                "https://publisher.example/feed?signature=secret", "https://publisher.example:8080/feed"):
        with pytest.raises(ValueError):
            configure_journal(store, config, "中文别名", "rss", url=url, feed_title="English Journal", runner=feed)
    assert not calls
    configure_journal(store, config, "中文别名", "rss", url="https://publisher.example/feed",
                      feed_title="English Journal", runner=feed)
    assert len(calls) == 1 and subscription_views(config)[-1]["enabled"]


def test_builtin_can_be_paused_and_restored_without_retaining_override_url(tmp_path):
    store, config = Store(tmp_path), defaults()
    configure_journal(store, config, "Built-in", "rss", url="https://publisher.example/rss",
                      runner=lambda *a: DiscoveryResult())
    toggle_journal(store, config, "Built-in", False)
    configure_journal(store, config, "Built-in", "builtin")
    assert config["journals"][0]["sources"] == ["official_toc"]
    assert "rss_url" not in config["journals"][0]
    with pytest.raises(ValueError):
        toggle_journal(store, config, "Pending", True)
    with pytest.raises(ValueError):
        configure_journal(store, config, "New", "builtin")


def test_metadata_probe_confirms_issn_and_rejects_mismatches(monkeypatch):
    monkeypatch.setattr("sociolit.subscriptions._request", lambda *a, **k: httpx.Response(200,
                        json={"message": {"title": "ASR", "ISSN": ["0003-1224"]}}))
    assert probe_journal("crossref", ["0003-1224"]) == "ASR"
    with pytest.raises(ValueError):
        probe_journal("crossref", ["0002-9602"])
    monkeypatch.delenv("OPENALEX_API_KEY", raising=False)
    with pytest.raises(ValueError, match="OPENALEX_API_KEY"):
        probe_journal("openalex", ["0003-1224"])


def test_subscription_api_auth_origin_busy_and_persistence(tmp_path, monkeypatch):
    monkeypatch.setattr("sociolit.subscriptions._request", lambda *a, **k: httpx.Response(200,
                        json={"message": {"title": "ASR", "ISSN": ["0003-1224"]}}))
    store = Store(tmp_path)
    app = create_app(store, defaults())
    with TestClient(app, base_url="http://127.0.0.1") as client:
        headers = {"X-Sociolit-Token": client.get("/api/status").json()["token"]}
        payload = {"name": "ASR", "provider": "crossref", "issns": ["0003-1224"]}
        assert client.post("/api/journals", json=payload).status_code == 403
        assert client.post("/api/journals", headers=dict(headers, Origin="https://foreign.example"), json=payload).status_code == 403
        app.state.operation_lock.acquire()
        try:
            assert client.post("/api/journals", headers=headers, json=payload).status_code == 409
        finally:
            app.state.operation_lock.release()
        response = client.post("/api/journals", headers=headers, json=payload)
        assert response.status_code == 200 and response.json()["source_title"] == "ASR"
        assert client.get("/api/journals", headers=headers).json()[-1]["name"] == "ASR"
        assert client.post("/api/journals/toggle", headers=headers, json={"name": "ASR", "enabled": False}).status_code == 200
        assert not client.get("/api/status").json()["journals"][-1]["enabled"]
    restarted = defaults()
    apply_feeds(Store(tmp_path), restarted)
    assert not restarted["journals"][-1]["enabled"]
