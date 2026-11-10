"""Private, explicitly verified public RSS endpoints; never an access bypass."""
from datetime import date, timedelta
from urllib.parse import parse_qsl, urlsplit

from .discovery import run_discovery


def apply_feeds(store, config):
    for journal in config.get("journals", []):
        saved = store.state("journal-feed:" + journal["name"])
        if saved:
            journal.update(enabled=saved["enabled"], rss_url=saved["url"], sources=["rss"],
                           required_feed_title=journal["name"], status="validated_rss" if saved["enabled"] else "paused_rss")
    return config


def configure_feed(store, config, name, url, enabled=True, *, runner=run_discovery):
    journal = next((j for j in config.get("journals", []) if j["name"] == name), None)
    if journal is None:
        raise ValueError("只能配置已登记的期刊。")
    parsed = urlsplit(url)
    forbidden = {"token", "key", "api_key", "access_token", "password", "auth", "authorization"}
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.fragment or forbidden.intersection(k.lower() for k, _ in parse_qsl(parsed.query))):
        raise ValueError("请输入公开 HTTPS RSS 地址，不要填写账号、密码或认证令牌。")
    candidate = dict(journal, enabled=True, sources=["rss"], rss_url=url, required_feed_title=name)
    today = date.today()
    result = runner([candidate], today-timedelta(days=90), today)
    if not result.complete:
        raise ValueError("订阅未通过检查：" + "; ".join(result.errors))
    store.set_state("journal-feed:" + name, {"url": url, "enabled": enabled, "validated": today.isoformat()})
    apply_feeds(store, config)
    return {"saved": True, "records_in_window": len(result.records), "enabled": enabled}
