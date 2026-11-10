import json
from datetime import date

import pytest
from filelock import FileLock, Timeout

from sociolit.discovery import DiscoveryResult
from sociolit.scheduler import discover_due
from sociolit.store import Store


def _config(sources=None):
    return {"discovery": {"lookback_days": 30, "overlap_days": 7}, "journals": [
        {"name": "Synthetic Journal", "issns": ["1234-5678"], "enabled": True,
         "sources": sources or ["crossref"]}]}


def _record():
    return {"title": "Synthetic care and employment", "authors": ["Test Author"],
            "year": "2026", "doi": "10.1234/synthetic", "journal": "Synthetic Journal",
            "published_date": "2026-09-01", "sources": ["crossref"], "source_ids": ["synthetic"]}


def _watermarks(store):
    with store.connect() as db:
        return {row["key"]: json.loads(row["value"]) for row in db.execute(
            "SELECT key,value FROM state WHERE key LIKE 'discovery:%'")}


def test_monthly_skip_next_month_and_persistent_dedup(tmp_path):
    store = Store(tmp_path / "state")
    calls = []
    def runner(subscriptions, since, until, **kwargs):
        calls.append((since, until))
        return DiscoveryResult(records=[_record()], since=since.isoformat(), until=until.isoformat())
    first = discover_due(store, _config(), today=date(2026, 9, 1), runner=runner)
    assert first["new"] == 1 and first["complete"]
    second = discover_due(store, _config(), today=date(2026, 9, 20), runner=runner)
    assert second["skipped"] and len(calls) == 1
    third = discover_due(store, _config(), today=date(2026, 10, 1), runner=runner)
    assert third["new"] == 0 and third["updated"] == 0 and third["total"] == 1
    assert len(calls) == 2
    assert len(store.search("care")) == 1


def test_failed_source_does_not_advance_watermark_and_retries_same_month(tmp_path):
    store = Store(tmp_path / "state")
    calls = []
    fail = [True]
    def runner(subscriptions, since, until, **kwargs):
        source = subscriptions[0]["sources"][0]
        calls.append(source)
        errors = ["Synthetic Journal/rss: network request failed"] if source == "rss" and fail[0] else []
        return DiscoveryResult(errors=errors, since=since.isoformat(), until=until.isoformat())
    config = _config(["crossref", "rss"])
    result = discover_due(store, config, today=date(2026, 11, 1), runner=runner)
    assert not result["complete"] and len(_watermarks(store)) == 1
    assert json.loads((store.directory / "discovery/digests/records.json").read_text(encoding="utf-8"))["complete"] is False
    fail[0] = False
    result = discover_due(store, config, today=date(2026, 11, 2), runner=runner)
    assert result["complete"] and result["attempted_sources"] == 1
    assert calls == ["crossref", "rss", "rss"]
    assert len(_watermarks(store)) == 2


def test_missed_months_catch_up_from_last_success_not_fixed_window(tmp_path):
    store = Store(tmp_path / "state")
    calls = []
    fail = [False]
    def runner(subscriptions, since, until, **kwargs):
        calls.append((since, until))
        return DiscoveryResult(errors=["temporary failure"] if fail[0] else [],
                               since=since.isoformat(), until=until.isoformat())
    discover_due(store, _config(), today=date(2026, 7, 1), runner=runner)
    fail[0] = True
    discover_due(store, _config(), today=date(2026, 11, 1), runner=runner)
    assert calls[-1][0] == date(2026, 6, 24)
    assert list(_watermarks(store).values()) == ["2026-07-01"]
    fail[0] = False
    discover_due(store, _config(), today=date(2026, 11, 2), runner=runner)
    assert calls[-1][0] == date(2026, 6, 24)
    assert list(_watermarks(store).values()) == ["2026-11-02"]


def test_no_enabled_sources_is_explicit_noop_with_reports(tmp_path):
    store = Store(tmp_path / "state")
    def forbidden(*args, **kwargs):
        raise AssertionError("disabled subscriptions must never request the network")
    result = discover_due(store, {"journals": [{"name": "Pending Journal", "enabled": False}]},
                          today=date(2026, 11, 6), runner=forbidden, output_dir=tmp_path / "report")
    assert result["attempted_sources"] == 0 and result["complete"]
    assert any("No source" in warning for warning in result["warnings"])
    assert (tmp_path / "report/digest.md").is_file()
    assert (tmp_path / "report/records.json").is_file()
    assert not _watermarks(store)


def test_enabled_journal_without_sources_reports_configuration_error(tmp_path):
    store = Store(tmp_path / "state")
    def forbidden(*args, **kwargs):
        raise AssertionError("a source-free configuration must not use the network")
    result = discover_due(store, {"journals": [{"name": "Broken Journal", "enabled": True, "sources": []}]},
                          today=date(2026, 11, 6), runner=forbidden)
    assert result["complete"] is False
    assert result["errors"]
    assert not _watermarks(store)


def test_discovery_keeps_zotero_sync_summary(tmp_path):
    store = Store(tmp_path / "state")
    previous = {"items_changed": 3, "files_indexed": 2, "warnings": ["synthetic warning"]}
    store.set_state("last_import", previous)
    def runner(subscriptions, since, until, **kwargs):
        return DiscoveryResult(records=[_record()], since=since.isoformat(), until=until.isoformat())
    discover_due(store, _config(), today=date(2026, 11, 6), runner=runner)
    assert store.state("last_import") == previous


def test_discovery_does_not_commit_cache_while_library_is_busy(tmp_path):
    store = Store(tmp_path / "state")
    def runner(subscriptions, since, until, **kwargs):
        return DiscoveryResult(records=[_record()], since=since.isoformat(), until=until.isoformat())
    with FileLock(str(store.directory / "library.lock")):
        with pytest.raises(Timeout):
            discover_due(store, _config(), today=date(2026, 11, 6), runner=runner)
    assert not (store.directory / "discovery/metadata-cache.json").exists()
    assert not _watermarks(store)
