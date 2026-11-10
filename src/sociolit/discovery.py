"""Bounded, metadata-only journal discovery. No attachment download or private input."""
from __future__ import annotations

import hashlib
import html
import ipaddress
import json
import os
import re
import socket
import time
import unicodedata
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import unquote, urljoin, urlsplit

import httpx
from defusedxml import ElementTree


class DiscoveryError(RuntimeError):
    """A deliberately sanitized error, safe for public workflow logs."""


@dataclass
class DiscoveryResult:
    records: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    since: str = ""
    until: str = ""

    @property
    def complete(self) -> bool:
        return not self.errors


def canonicalize_doi(value: str | None) -> str:
    value = unquote(str(value or "")).strip()
    value = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", value, flags=re.I)
    value = re.sub(r"^doi\s*:\s*", "", value, flags=re.I).strip().lower()
    return value if re.fullmatch(r"10\.\d{4,9}/[^\s<>]+", value) else ""


def _text(value: Any) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]*>", "", str(value or ""))).split())


def _public_link(value: Any) -> str:
    value = str(value or "").strip()
    try:
        parsed = urlsplit(value)
        if parsed.scheme in {"http", "https"} and parsed.hostname and not parsed.username and not parsed.password:
            return value
    except ValueError:
        pass
    return ""


def _fingerprint(record: dict[str, Any]) -> str:
    # No fuzzy merges: same normalized title, publication year and first author.
    title = re.sub(r"\W+", "", unicodedata.normalize("NFKC", record.get("title", "")).casefold())
    authors = record.get("authors", [])
    author = re.sub(r"\W+", "", unicodedata.normalize("NFKC", authors[0]).casefold()) if authors else ""
    year = record.get("year")
    return f"{title}|{year}|{author}" if title and year and author else ""


def _normalize(record: dict[str, Any]) -> dict[str, Any]:
    doi = canonicalize_doi(record.get("doi"))
    authors = [_text(a) for a in record.get("authors", []) if _text(a)]
    normalized = {
        "title": _text(record.get("title")), "authors": authors,
        "year": str(record.get("year") or ""), "doi": doi,
        "journal": _text(record.get("journal")),
        "url": "https://doi.org/" + doi if doi else _public_link(record.get("url")),
        "published_date": _text(record.get("published_date")),
        "sources": sorted(set(record.get("sources", []))),
        "source_ids": sorted(set(str(x) for x in record.get("source_ids", []) if x)),
        "issns": sorted(set(str(x) for x in record.get("issns", []) if x)),
    }
    identity = _fingerprint(normalized) or "|".join(normalized["source_ids"]) or normalized["url"] or normalized["title"]
    normalized["id"] = "doi:" + doi if doi else "meta:" + hashlib.sha256(identity.encode()).hexdigest()[:24]
    return normalized


def merge_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge DOI equivalents and strong exact matches, never differing DOIs."""
    merged: list[dict[str, Any]] = []
    for raw in records:
        record = _normalize(raw)
        if not record["title"]:
            continue
        by_doi = [i for i, old in enumerate(merged) if record["doi"] and old["doi"] == record["doi"]]
        fp = _fingerprint(record)
        candidates = by_doi or [i for i, old in enumerate(merged)
            if (record["id"] == old["id"] or (fp and _fingerprint(old) == fp))
            and not (record["doi"] and old["doi"] and record["doi"] != old["doi"])]
        if len(candidates) != 1:
            merged.append(record)
            continue
        old = merged[candidates[0]]
        for key in ("sources", "source_ids", "issns"):
            record[key] = sorted(set(old[key] + record[key]))
        for key in ("title", "authors", "year", "doi", "journal", "url", "published_date"):
            if not record[key]:
                record[key] = old[key]
        merged[candidates[0]] = _normalize(record)
    return sorted(merged, key=lambda record: (record["published_date"], record["title"], record["id"]), reverse=True)


def _retry_delay(value: str | None, attempt: int) -> float:
    if value:
        try:
            delay = float(value)
        except ValueError:
            try:
                parsed = parsedate_to_datetime(value)
                delay = (parsed - datetime.now(timezone.utc)).total_seconds()
            except (ValueError, TypeError):
                delay = 2 ** attempt
        if delay > 60:
            raise DiscoveryError("rate limit requests a long wait; retry this source later")
        return max(0.0, delay)
    return float(2 ** attempt)


def _request(client: httpx.Client, url: str, *, params: dict | None = None,
             headers: dict | None = None, sleep: Callable = time.sleep,
             max_bytes: int = 8_000_000) -> httpx.Response:
    for attempt in range(3):
        sleep(0.25)  # Sequential and below the published default API request limits.
        try:
            with client.stream("GET", url, params=params, headers=headers, timeout=30,
                               follow_redirects=False) as response:
                if response.status_code in {429, 500, 502, 503, 504}:
                    if attempt == 2:
                        raise DiscoveryError(f"HTTP {response.status_code}; retries exhausted")
                    delay = _retry_delay(response.headers.get("Retry-After"), attempt)
                    sleep(delay)
                    continue
                if response.status_code >= 400:
                    raise DiscoveryError(f"HTTP {response.status_code}")
                chunks, size = [], 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > max_bytes:
                        raise DiscoveryError("response exceeds the 8 MB safety limit")
                    chunks.append(chunk)
                decoded_headers = dict(response.headers)
                decoded_headers.pop("content-encoding", None)
                decoded_headers.pop("content-length", None)
                return httpx.Response(response.status_code, headers=decoded_headers,
                                      content=b"".join(chunks), request=response.request)
        except httpx.RequestError:
            if attempt == 2:
                raise DiscoveryError("network request failed after 3 attempts") from None
            sleep(float(2 ** attempt))
    raise DiscoveryError("request failed")


def _json(response: httpx.Response) -> dict:
    try:
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError
        return data
    except (ValueError, UnicodeError):
        raise DiscoveryError("response was not a JSON object") from None


def _date_parts(value: Any) -> str:
    parts = (value or {}).get("date-parts", [[]])[0]
    if not parts:
        return ""
    return "-".join(str(n).zfill(4 if index == 0 else 2) for index, n in enumerate(parts[:3]))


def _crossref(client: httpx.Client, subscription: dict, since: date, until: date,
              max_pages: int, sleep: Callable) -> list[dict]:
    output = []
    for issn in _issns(subscription):
        cursor, seen = "*", set()
        for _page in range(max_pages):
            params = {"filter": f"from-index-date:{since},until-index-date:{until}",
                      "rows": 100, "cursor": cursor}
            email = os.environ.get("CROSSREF_MAILTO")
            if email:
                params["mailto"] = email
            payload = _json(_request(client, f"https://api.crossref.org/journals/{issn}/works", params=params, sleep=sleep))
            message = payload.get("message", {})
            items = message.get("items", [])
            if not isinstance(items, list):
                raise DiscoveryError("Crossref items has an invalid shape")
            for item in items:
                published = _date_parts(item.get("published") or item.get("issued"))
                output.append({"title": (item.get("title") or [""])[0],
                    "authors": [" ".join(filter(None, [a.get("given"), a.get("family")])) or a.get("name", "") for a in item.get("author", [])],
                    "year": published[:4], "published_date": published,
                    "doi": item.get("DOI", ""), "journal": (item.get("container-title") or [subscription.get("name", "")])[0],
                    "url": item.get("URL", ""), "sources": ["crossref"],
                    "source_ids": [item.get("DOI", "")], "issns": item.get("ISSN", [issn])})
            next_cursor = message.get("next-cursor")
            if not items or not next_cursor or len(items) < 100:
                break
            if next_cursor == cursor or next_cursor in seen:
                raise DiscoveryError("Crossref repeated a pagination cursor; run incomplete")
            seen.add(cursor)
            cursor = next_cursor
        else:
            raise DiscoveryError("Crossref page limit reached; shorten the date window or raise max_pages")
    return output


def _issns(subscription: dict) -> list[str]:
    values = subscription.get("issns", [])
    if not values:
        raise DiscoveryError("this source requires at least one journal ISSN")
    result = []
    for value in values:
        value = str(value).upper().replace("-", "")
        if not re.fullmatch(r"\d{7}[\dX]", value):
            raise DiscoveryError("invalid journal ISSN")
        result.append(value[:4] + "-" + value[4:])
    return sorted(set(result))


def _openalex(client: httpx.Client, subscription: dict, since: date, until: date,
              max_pages: int, sleep: Callable) -> list[dict]:
    key = os.environ.get("OPENALEX_API_KEY", "")
    if not key:
        raise DiscoveryError("OPENALEX_API_KEY is required for reliable cursor paging; set it in the environment")
    issns = _issns(subscription)
    cursor, seen, output = "*", set(), []
    for _page in range(max_pages):
        params = {"filter": "primary_location.source.issn:" + "|".join(issns)
                  + f",from_publication_date:{since},to_publication_date:{until}",
                  "per_page": 100, "cursor": cursor,
                  "select": "id,doi,title,publication_date,authorships,primary_location"}
        payload = _json(_request(client, "https://api.openalex.org/works", params=params,
                                headers={"Authorization": "Bearer " + key}, sleep=sleep))
        items = payload.get("results", [])
        if not isinstance(items, list):
            raise DiscoveryError("OpenAlex results has an invalid shape")
        for item in items:
            location = item.get("primary_location") or {}
            source = location.get("source") or {}
            published = item.get("publication_date") or ""
            output.append({"title": item.get("title", ""),
                "authors": [(a.get("author") or {}).get("display_name", "") for a in item.get("authorships", [])],
                "year": published[:4], "published_date": published,
                "doi": item.get("doi", ""), "journal": source.get("display_name", subscription.get("name", "")),
                "url": location.get("landing_page_url") or item.get("doi") or item.get("id"),
                "sources": ["openalex"], "source_ids": [item.get("id", "")],
                "issns": source.get("issn") or issns})
        next_cursor = (payload.get("meta") or {}).get("next_cursor")
        if not items or not next_cursor:
            break
        if next_cursor == cursor or next_cursor in seen:
            raise DiscoveryError("OpenAlex repeated a pagination cursor; run incomplete")
        seen.add(cursor)
        cursor = next_cursor
    else:
        raise DiscoveryError("OpenAlex page limit reached; shorten the date window or raise max_pages")
    return output


def _validate_feed_url(url: str) -> None:
    try:
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.port not in (None, 443):
            raise DiscoveryError("RSS requires a public HTTPS URL without embedded credentials")
        addresses = socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(address[4][0]).is_global for address in addresses):
            raise DiscoveryError("RSS URLs must resolve only to public internet addresses")
    except (ValueError, socket.gaierror):
        raise DiscoveryError("RSS URL is invalid or its hostname cannot be resolved") from None


def _entry_date(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        try:
            return parsedate_to_datetime(value).date().isoformat()
        except (ValueError, TypeError):
            return ""


def _rss(client: httpx.Client, subscription: dict, since: date, until: date,
         sleep: Callable) -> list[dict]:
    url = subscription.get("rss_url", "")
    for _redirect in range(4):
        _validate_feed_url(url)
        response = _request(client, url, sleep=sleep)
        if response.status_code in {301, 302, 303, 307, 308}:
            url = urljoin(url, response.headers.get("Location", ""))
            continue
        break
    else:
        raise DiscoveryError("RSS exceeded the redirect limit")
    try:
        root = ElementTree.fromstring(response.content)
    except Exception:
        raise DiscoveryError("RSS is invalid XML or contains unsafe XML entities") from None
    if root.tag.rsplit("}", 1)[-1].lower() not in {"rss", "feed", "rdf"}:
        raise DiscoveryError("RSS URL returned a document that is not an RSS/Atom feed")
    output = []
    entries = [element for element in root.iter() if element.tag.rsplit("}", 1)[-1] in {"item", "entry"}]
    for entry in entries:
        fields: dict[str, list[Any]] = {}
        for element in entry:
            fields.setdefault(element.tag.rsplit("}", 1)[-1], []).append(element)
        def value(*names: str, fields=fields) -> str:
            for name in names:
                if fields.get(name):
                    return "".join(fields[name][0].itertext()).strip()
            return ""
        published = _entry_date(value("published", "pubDate", "date", "updated"))
        if published and not since.isoformat() <= published <= until.isoformat():
            continue
        link = ""
        for element in fields.get("link", []):
            if element.attrib.get("rel", "alternate") == "alternate":
                link = element.attrib.get("href") or (element.text or "")
                break
        identifiers = [value("doi"), value("identifier"), link, value("guid", "id")]
        doi = next((canonicalize_doi(candidate) for candidate in identifiers if canonicalize_doi(candidate)), "")
        author = value("creator", "author")
        output.append({"title": value("title"), "authors": [author] if author else [],
            "year": published[:4], "published_date": published, "doi": doi,
            "journal": subscription.get("name", ""), "url": urljoin(url, link) if link else "",
            "sources": ["rss"], "source_ids": [value("guid", "id") or link],
            "issns": subscription.get("issns", [])})
    return output


def run_discovery(subscriptions: list[dict], since: date, until: date, *,
                  client: httpx.Client | None = None, max_pages: int = 20,
                  sleep: Callable = time.sleep) -> DiscoveryResult:
    """Fetch enabled journals; a failed source is visible and never marked complete.

    `since`/`until` bound Crossref's index date and OpenAlex/RSS publication date.
    RSS entries without dates are retained, then deduplicated by persistent state.
    """
    if since > until or not 1 <= max_pages <= 1000:
        raise ValueError("invalid date window or max_pages (allowed 1..1000)")
    result = DiscoveryResult(since=since.isoformat(), until=until.isoformat())
    owns_client = client is None
    client = client or httpx.Client(trust_env=False, headers={"User-Agent": "Sociolit/0.1 (journal metadata discovery)"})
    try:
        for subscription in subscriptions:
            if not subscription.get("enabled", False):
                continue
            label = _text(subscription.get("name", "journal"))[:120]
            sources = subscription.get("sources", ["crossref"])
            if not sources:
                result.errors.append(f"{label}: no metadata sources configured")
            for source in dict.fromkeys(sources):
                try:
                    if source == "crossref":
                        records = _crossref(client, subscription, since, until, max_pages, sleep)
                    elif source == "openalex":
                        records = _openalex(client, subscription, since, until, max_pages, sleep)
                        result.warnings.append(f"{label}: OpenAlex uses publication dates; late-indexed older records and older metadata corrections may fall outside this window")
                    elif source == "rss":
                        records = _rss(client, subscription, since, until, sleep)
                        result.warnings.append(f"{label}: RSS exposes the publisher's current feed only; monthly polling can miss entries that expire sooner")
                    elif source == "cass_current_toc":
                        from .cass_toc import cass_current_toc
                        records = cass_current_toc(client, subscription, request=_request, sleep=sleep)
                        result.warnings.append(f"{label}：仅检查官网当前一期；长时间未运行可能漏掉中间期次，未提供准确发表日。")
                    elif source == "official_toc":
                        from .official_toc import official_toc
                        records = official_toc(client, subscription, since, until, request=_request, sleep=sleep, max_pages=max_pages)
                        result.warnings.append(f"{label}：已检查官网期刊目录，目录以外的网络首发论文未覆盖。")
                    else:
                        raise DiscoveryError("unsupported metadata source")
                    result.records.extend(records)
                except DiscoveryError as exc:
                    result.errors.append(f"{label}/{source}: {exc}")
                except Exception as exc:
                    # No raw exception text: HTTP exceptions can contain API keys/URLs.
                    result.errors.append(f"{label}/{source}: invalid source response ({type(exc).__name__})")
        result.records = merge_records(result.records)
        return result
    finally:
        if owns_client:
            client.close()


def _atomic_json(path: Path, data: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _markdown(value: Any) -> str:
    return re.sub(r"([\\`*_{}\[\]()#+.!|>])", r"\\\1", str(value)).replace("\n", " ")


def persist_discovery(result: DiscoveryResult, state_dir: str | Path, *,
                      output_dir: str | Path | None = None) -> dict[str, Any]:
    """Persist only the allowlisted bibliographic metadata, plus a local digest."""
    state_dir = Path(state_dir)
    output_dir = Path(output_dir) if output_dir is not None else state_dir / "digests"
    state_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    cache_path = state_dir / "metadata-cache.json"
    old = []
    if cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            old = merge_records(cached["records"])
        except (ValueError, KeyError, TypeError):
            raise DiscoveryError("metadata cache is invalid; preserve it and restore a backup") from None
    merged = merge_records(old + result.records)
    new_records, updated_records = [], []
    for record in merged:
        fp = _fingerprint(record)
        candidates = [previous for previous in old if record["id"] == previous["id"]
            or (fp and fp == _fingerprint(previous)
                and not (record["doi"] and previous["doi"] and record["doi"] != previous["doi"]))]
        if not candidates:
            new_records.append(record)
        elif len(candidates) == 1 and record != candidates[0]:
            updated_records.append(record)
    _atomic_json(cache_path, {"version": 1, "records": merged})
    digest_path = output_dir / "digest.md"
    metadata_path = output_dir / "records.json"
    report = {"since": result.since, "until": result.until, "complete": result.complete,
              "new": len(new_records), "updated": len(updated_records), "total": len(merged),
              "errors": result.errors, "warnings": list(dict.fromkeys(result.warnings)),
              "records": merge_records(result.records)}
    _atomic_json(metadata_path, report)
    lines = ["# 期刊文献更新", "", f"窗口：{result.since} — {result.until}", "",
             f"新增 {len(new_records)} 篇；更新 {len(updated_records)} 篇；累计 {len(merged)} 篇。", "",
             "状态：" + ("已完成" if result.complete else "部分来源失败，请重试；本次不能作为完整更新。"), ""]
    for heading, records in (("新增", new_records), ("更新", updated_records)):
        lines.extend(["## " + heading, ""])
        for record in records:
            title = _markdown(record["title"])
            # Percent-escape delimiters so source-supplied URLs cannot alter Markdown.
            url = record["url"].replace("(", "%28").replace(")", "%29").replace("<", "%3C").replace(">", "%3E").replace(" ", "%20")
            link = f"[{title}]({url})" if url else title
            lines.append(f"- {link} — {_markdown(record['journal'])}，{_markdown(record['published_date'])}")
        if not records:
            lines.append("无。")
        lines.append("")
    for heading, messages in (("来源错误", result.errors), ("覆盖范围说明", report["warnings"])):
        if messages:
            lines.extend(["## " + heading, ""] + ["- " + _markdown(message) for message in messages] + [""])
    lines.append("仅收集书目元数据和原站链接；没有下载论文全文。")
    temporary = digest_path.with_suffix(".md.tmp")
    temporary.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.replace(temporary, digest_path)
    # Keep each completed or partial report for longitudinal review. The
    # public report schema excludes private library data and API secrets.
    history = state_dir / "history"
    history.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    (history / f"{stamp}.md").write_text(digest_path.read_text(encoding="utf-8"), encoding="utf-8")
    _atomic_json(history / f"{stamp}.json", report)
    return {"new": len(new_records), "updated": len(updated_records), "total": len(merged),
            "digest_path": str(digest_path), "metadata_path": str(metadata_path)}
