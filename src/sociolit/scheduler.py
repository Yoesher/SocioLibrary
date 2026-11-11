import json
from datetime import date, timedelta
from hashlib import sha256

from filelock import FileLock

from .discovery import DiscoveryResult, merge_records, persist_discovery, run_discovery
from .indexing import import_snapshot
from .zotero import Snapshot


def discover_due(store, config, *, force=False, output_dir=None, today=None, runner=run_discovery):
    from .subscriptions import apply_feeds
    apply_feeds(store, config)
    today = today or date.today()
    settings = config.get("discovery", {})
    lookback = int(settings.get("lookback_days", 90))
    overlap = int(settings.get("overlap_days", 7))
    if lookback < 1 or overlap < 0:
        raise ValueError("Invalid discovery window")
    state_dir = store.directory / "discovery"
    state_dir.mkdir(parents=True, exist_ok=True)
    with FileLock(str(state_dir / "update.lock"), timeout=1):
        result = DiscoveryResult(since=(today-timedelta(days=lookback)).isoformat(), until=today.isoformat())
        successful = []
        attempted = 0
        for journal in config.get("journals", []):
            if not journal.get("enabled", False):
                continue
            sources = journal.get("sources", [])
            if not sources:
                result.errors.append(f"{journal.get('name', 'journal')}: no metadata sources configured")
                continue
            for source in sources:
                identity = {"name": journal.get("name"), "issns": journal.get("issns", []),
                            "rss_url": journal.get("rss_url", ""), "source": source}
                key = "discovery:" + sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
                previous = store.state(key)
                if not force and previous and previous[:7] == today.isoformat()[:7]:
                    continue
                since = today-timedelta(days=lookback)
                if previous:
                    since = min(since, date.fromisoformat(previous)-timedelta(days=overlap))
                one = dict(journal, sources=[source])
                response = runner([one], since, today, max_pages=int(settings.get("max_pages", 20)))
                attempted += 1
                result.since = min(result.since, since.isoformat())
                result.records.extend(response.records)
                result.errors.extend(response.errors)
                result.warnings.extend(response.warnings)
                if response.complete:
                    successful.append(key)
        if not attempted:
            result.warnings.append("No source was due or enabled. Registered pending journals are not active subscriptions.")
            # Keep the last real digest available when a daily check finds nothing due.
            if not force and not result.errors and store.state("last_discovery"):
                return dict(store.state("last_discovery"), skipped=True)
        result.records = merge_records(result.records)
        # Do not mutate the cache/report before confirming that the shared
        # library can accept the corresponding searchable records.
        with FileLock(str(store.directory / "library.lock"), timeout=1):
            summary = persist_discovery(result, state_dir, output_dir=output_dir)
            records = json.loads((state_dir / "metadata-cache.json").read_text(encoding="utf-8"))["records"]
            items = [dict(key=r["id"], title=r["title"], authors=r["authors"], year=r["year"],
                          doi=r["doi"], abstract="", tags=[r["journal"]], item_type="discovery", raw=r) for r in records]
            import_snapshot(store, Snapshot("journals:public-metadata", items, [], True), assume_locked=True)
            from .journal_inbox import sync
            sync(store)
            for key in successful:
                store.set_state(key, today.isoformat())
            summary.update(complete=result.complete, errors=result.errors, warnings=result.warnings,
                           checked=today.isoformat(), attempted_sources=attempted)
            store.set_state("last_discovery", summary)
        return summary
