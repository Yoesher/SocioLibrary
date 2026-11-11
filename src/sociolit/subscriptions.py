"""Private, explicitly verified public RSS endpoints; never an access bypass."""
import os
import re
from copy import deepcopy
from datetime import date, timedelta
from urllib.parse import parse_qsl, urlsplit

import httpx

from .discovery import DiscoveryError, _json, _request, run_discovery


def apply_feeds(store, config):
    defaults = config.setdefault("_journal_defaults", deepcopy(config.get("journals", [])))
    journals = {j["name"]: deepcopy(j) for j in defaults}
    for journal in journals.values():
        saved = store.state("journal-feed:" + journal["name"])
        if saved:
            journal.update(enabled=saved["enabled"], rss_url=saved["url"], sources=["rss"],
                           required_feed_title=journal["name"], status="validated_rss" if saved["enabled"] else "paused_rss")
    journals.update(deepcopy(store.state("journal-subscriptions") or {}))
    config["journals"] = list(journals.values())
    return config


def subscription_views(config):
    defaults = {j["name"]: j for j in config.get("_journal_defaults", [])}
    output = []
    for journal in config.get("journals", []):
        sources = journal.get("sources", [])
        provider = sources[0] if len(sources) == 1 and sources[0] in {"rss", "crossref", "openalex"} else "builtin"
        output.append({"name": journal["name"], "enabled": journal.get("enabled", False),
                       "status": journal.get("status", ""), "provider": provider,
                       "rss_url": journal.get("rss_url", ""), "issns": journal.get("issns", []),
                       "feed_title": journal.get("required_feed_title", journal["name"]),
                       "source_title": journal.get("source_title", ""),
                       "builtin_available": bool(defaults.get(journal["name"], {}).get("sources")),
                       "homepage": journal.get("homepage", "")})
    return output


def _public_feed_setting(url):
    parsed = urlsplit(url)
    forbidden = {"token", "key", "api_key", "apikey", "api-key", "access_token", "password", "auth",
                 "authorization", "signature", "sig", "credential", "session", "ticket"}
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.port not in (None, 443) or parsed.fragment
            or forbidden.intersection(k.lower() for k, _ in parse_qsl(parsed.query))):
        raise ValueError("请输入公开 HTTPS RSS 地址，不要填写账号、密码或认证令牌。")


def _journal_issns(values):
    output = []
    for value in values:
        value = value.strip().upper().replace("-", "")
        if not re.fullmatch(r"\d{7}[\dX]", value):
            raise ValueError("ISSN 应为 8 位，例如 0003-1224。")
        checksum = sum(int(n) * (8-i) for i, n in enumerate(value[:7])) + (10 if value[-1] == "X" else int(value[-1]))
        if checksum % 11:
            raise ValueError("ISSN 校验位不正确，请从期刊官网核对。")
        output.append(value[:4] + "-" + value[4:])
    if not 1 <= len(output) <= 2:
        raise ValueError("请填写 1 至 2 个 ISSN（印刷版、电子版）。")
    return sorted(set(output))


def probe_journal(provider, issns):
    """Resolve exact journal identifiers, without downloading papers or exposing keys."""
    if provider == "openalex" and not os.environ.get("OPENALEX_API_KEY"):
        raise ValueError("OpenAlex 需要在本机环境配置 OPENALEX_API_KEY；可先选择无需密钥的 Crossref。")
    titles = []
    with httpx.Client(trust_env=False) as client:
        for issn in issns:
            if provider == "crossref":
                payload = _json(_request(client, f"https://api.crossref.org/journals/{issn}"))
                message = payload.get("message", {})
                title = message.get("title", "")
                matched = message.get("ISSN", [])
            else:
                payload = _json(_request(client, f"https://api.openalex.org/sources/issn:{issn}",
                                         params={"api_key": os.environ["OPENALEX_API_KEY"]}))
                title = payload.get("display_name", "")
                matched = payload.get("issn", [])
            if not isinstance(title, str) or not title.strip() or issn not in (matched or []):
                raise ValueError("元数据源未能确认该 ISSN，请核对或改用期刊官网 RSS。")
            titles.append(title.strip()[:300])
    if len(set(titles)) != 1:
        raise ValueError("两个 ISSN 对应的期刊名称不同，请分别添加订阅。")
    return titles[0]


def configure_journal(store, config, name, provider, *, url="", issns=(), feed_title="",
                      runner=run_discovery, probe=probe_journal):
    name = name.strip()
    if not name or len(name) > 100 or any(ord(c) < 32 for c in name):
        raise ValueError("请填写 1 至 100 字的期刊名称。")
    apply_feeds(store, config)
    existing = {j["name"]: j for j in config["journals"]}
    if name not in existing and len(existing) >= 50:
        raise ValueError("最多配置 50 种期刊。")
    candidate = {"name": name, "enabled": True, "sources": [provider], "homepage": ""}
    today = date.today()
    count = None
    if provider == "builtin":
        base = next((j for j in config["_journal_defaults"] if j["name"] == name), None)
        if not base or not base.get("sources"):
            raise ValueError("该期刊没有内置来源，请选择 RSS 或 ISSN 元数据接入。")
        candidate = dict(base, enabled=True)
    elif provider == "rss":
        _public_feed_setting(url)
        title = (feed_title or name).strip()
        if not title or len(title) > 200 or any(ord(c) < 32 for c in title):
            raise ValueError("请填写有效的 RSS 频道刊名。")
        candidate.update(rss_url=url, required_feed_title=title, source_title=title, status="validated_rss")
        result = runner([candidate], today-timedelta(days=90), today)
        if not result.complete:
            raise ValueError("订阅未通过检查：" + "; ".join(result.errors))
        count = len(result.records)
    elif provider in {"crossref", "openalex"}:
        candidate["issns"] = _journal_issns(issns)
        try:
            candidate["source_title"] = probe(provider, candidate["issns"])
        except (DiscoveryError, httpx.RequestError):
            raise ValueError("元数据源连接失败或未收录该 ISSN；原订阅未改变，请稍后重试或改用官网 RSS。") from None
        candidate["status"] = "validated_metadata"
    else:
        raise ValueError("不支持的接入方式。")
    candidate["validated"] = today.isoformat()
    saved = store.state("journal-subscriptions") or {}
    saved[name] = candidate
    store.set_state("journal-subscriptions", saved)
    apply_feeds(store, config)
    return {"saved": True, "source_title": candidate.get("source_title", name), "records_in_window": count}


def toggle_journal(store, config, name, enabled):
    apply_feeds(store, config)
    candidate = next((deepcopy(j) for j in config["journals"] if j["name"] == name), None)
    if candidate is None:
        raise ValueError("订阅不存在。")
    if enabled and not candidate.get("sources"):
        raise ValueError("请先编辑并验证接入来源，再启用订阅。")
    candidate["enabled"] = enabled
    saved = store.state("journal-subscriptions") or {}
    saved[name] = candidate
    store.set_state("journal-subscriptions", saved)
    apply_feeds(store, config)
    return {"saved": True, "enabled": enabled}


def configure_feed(store, config, name, url, enabled=True, *, runner=run_discovery):
    apply_feeds(store, config)
    journal = next((j for j in config.get("journals", []) if j["name"] == name), None)
    if journal is None:
        raise ValueError("只能配置已登记的期刊。")
    _public_feed_setting(url)
    candidate = dict(journal, enabled=True, sources=["rss"], rss_url=url, required_feed_title=name)
    today = date.today()
    result = runner([candidate], today-timedelta(days=90), today)
    if not result.complete:
        raise ValueError("订阅未通过检查：" + "; ".join(result.errors))
    store.set_state("journal-feed:" + name, {"url": url, "enabled": enabled, "validated": today.isoformat()})
    overrides = store.state("journal-subscriptions") or {}
    if name in overrides:
        overrides[name] = dict(candidate, enabled=enabled, status="validated_rss" if enabled else "paused_rss")
        store.set_state("journal-subscriptions", overrides)
    apply_feeds(store, config)
    return {"saved": True, "records_in_window": len(result.records), "enabled": enabled}
