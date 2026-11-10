"""Restricted, metadata-only adapters for two public journal issue pages."""
from __future__ import annotations

import re
from datetime import date
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

# Fixed allowlist avoids arbitrary URLs, and each publisher's robots.txt is
# rechecked on every run. New sources need individual review and tests.
JOURNALS = {
    "1000-6087": ("人口研究", "rkyj.ruc.edu.cn", "https://rkyj.ruc.edu.cn/CN/1000-6087/current.shtml"),
    "1004-8804": ("社会", "www.society.shu.edu.cn", "https://www.society.shu.edu.cn/CN/1004-8804/current.shtml"),
}


class IssueParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.in_form = False
        self.capture = None
        self.parts = []
        self.href = ""
        self.issue_text = ""
        self.previous = ""
        self.articles = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = attrs.get("class", "").split()
        if tag == "form" and attrs.get("id", "").lower() == "abstractlist":
            self.in_form = True
        if tag == "div" and "njq" in classes:
            self.capture, self.parts = "issue", []
        elif tag == "a" and self.in_form and "biaoti" in classes:
            self.capture, self.parts, self.href = "title", [], attrs.get("href", "")
        elif tag == "dd" and self.in_form and "zuozhe" in classes:
            self.capture, self.parts = "author", []
        elif tag == "a" and not self.in_form and not self.capture:
            href = attrs.get("href", "")
            if re.search(r"(?:^|/)volumn/volumn_\d+\.shtml$", href):
                self.capture, self.parts, self.href = "previous", [], href

    def handle_data(self, data):
        if self.capture:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if tag == "form" and self.in_form:
            self.in_form = False
        end_tags = {"issue": "div", "title": "a", "author": "dd", "previous": "a"}
        if self.capture and tag == end_tags[self.capture]:
            value = " ".join("".join(self.parts).split())
            if self.capture == "issue":
                self.issue_text = value
            elif self.capture == "title":
                self.articles.append({"title": value, "url": self.href, "authors": []})
            elif self.capture == "author" and self.articles:
                self.articles[-1]["authors"] = [x.strip() for x in re.split(r"[,，;；]", value) if x.strip()]
            elif self.capture == "previous" and "上一期" in value:
                self.previous = self.href
            self.capture, self.parts = None, []


def _same_origin(url, hostname):
    parsed = urlsplit(url)
    return (parsed.scheme == "https" and parsed.hostname == hostname and parsed.port in (None, 443)
            and not parsed.username and not parsed.password and not parsed.query and not parsed.fragment)


def official_toc(client, subscription, since, until, *, request, sleep, max_pages):
    # The ISSN-to-host mapping is hardcoded rather than accepting arbitrary URLs.
    issns = subscription.get("issns", [])
    if len(issns) != 1 or issns[0] not in JOURNALS:
        raise ValueError("Official issue adapter supports only its individually reviewed journals")
    name, host, url = JOURNALS[issns[0]]
    if subscription.get("name") != name:
        raise ValueError("Journal name and ISSN do not match the reviewed source")
    robots_url = f"https://{host}/robots.txt"
    robots_response = request(client, robots_url, sleep=sleep)
    if robots_response.status_code != 200:
        raise ValueError("Publisher robots.txt unavailable")
    if not re.search(r"(?im)^\s*user-agent\s*:", robots_response.text):
        raise ValueError("Publisher robots.txt response is not a recognizable robots policy")
    robots = RobotFileParser()
    robots.parse(robots_response.text.splitlines())
    records, seen, last_date = [], set(), None
    for _ in range(max_pages):
        if not _same_origin(url, host) or url in seen or not robots.can_fetch("Sociolit", url):
            raise ValueError("Issue URL invalid, repeated, or disallowed by robots.txt")
        seen.add(url)
        response = request(client, url, sleep=sleep)
        if response.status_code != 200:
            raise ValueError("Issue URL did not return a normal page")
        parser = IssueParser()
        parser.feed(response.text)
        match = re.search(r"(\d{4})年\s*第\s*(\d+)\s*卷\s*第\s*(\d+)\s*期.*?刊出日期\s*[：:]\s*(\d{4}-\d{2}-\d{2})", parser.issue_text)
        if not match or not parser.articles:
            raise ValueError("Issue layout or publication date was not recognized")
        year, volume, issue, published = match.groups()
        issue_date = date.fromisoformat(published)
        if year != str(issue_date.year) or (last_date and issue_date >= last_date):
            raise ValueError("Issue chronology is inconsistent")
        last_date = issue_date
        for item in parser.articles:
            link = urljoin(url, item["url"])
            pattern = rf"/CN/Y{year}/V{int(volume)}/I{int(issue)}/[^/]+"
            if (not _same_origin(link, host) or not re.fullmatch(pattern, urlsplit(link).path)
                    or not item["title"] or item["title"].endswith(("...", "…")) or not item["authors"]):
                raise ValueError("Incomplete or inconsistent article metadata in official issue")
            records.append({"title": item["title"], "authors": item["authors"], "year": year,
                            "doi": "", "journal": name, "url": link, "published_date": published,
                            "sources": ["official_toc"], "source_ids": [link], "issns": issns})
        if issue_date < since:
            break
        if not parser.previous:
            raise ValueError("Previous-issue link missing before the requested backfill boundary")
        next_url = urljoin(url, parser.previous)
        if not _same_origin(next_url, host) or not re.fullmatch(r"/CN/volumn/volumn_\d+\.shtml", urlsplit(next_url).path):
            raise ValueError("Previous-issue link failed validation")
        url = next_url
    else:
        raise ValueError("Official issue backfill reached the page limit")
    return records
