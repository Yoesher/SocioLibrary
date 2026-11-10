"""Current-issue snapshots from two specifically reviewed CASS journal sites."""
from __future__ import annotations

import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

JOURNALS = {
    "1002-5936": ("社会学研究", "shxyj.ajcass.com"),
    "1000-7881": ("中国人口科学", "zgrkkx.ajcass.com"),
}


class CurrentIssueParser(HTMLParser):
    def __init__(self, mode):
        super().__init__(convert_charrefs=True)
        self.mode = mode
        self.depth = 0
        self.scope = 0
        self.scope_kind = "IssueList" if mode == "social" else "qk"
        self.year = ""
        self.issue = ""
        self.text_parts = []
        self.title = None
        self.title_depth = 0
        self.author_parts = []
        self.in_author = False
        self.row = None
        self.cell = None
        self.articles = []
        self.awaiting_author = False

    def handle_starttag(self, tag, attrs):
        self.depth += 1 if tag not in {"input", "img", "br", "meta", "link", "hr"} else 0
        a = dict(attrs)
        if tag == "input" and a.get("id") == "iYear":
            self.year = a.get("value", "")
        if tag == "input" and a.get("id") == "iIsue":
            self.issue = a.get("value", "")
        if tag == "div" and (a.get("id") == self.scope_kind or self.scope_kind in a.get("class", "").split()):
            self.scope = self.depth
        if not self.scope:
            return
        if self.mode == "social":
            if tag == "a" and re.fullmatch(r"/Magazine/Show\?id=\d+", a.get("href", "")) and a.get("id", "").startswith("a "):
                self.title = {"url": a["href"], "title": [], "authors": []}
                self.title_depth = self.depth
            elif tag == "span" and self.title is not None:
                self.in_author = True
        else:
            if tag == "tr":
                self.row = []
            elif tag == "td" and self.row is not None:
                self.cell = {"text": [], "link": ""}
            elif tag == "a" and self.cell is not None and re.fullmatch(r"/Magazine/Show\?id=\d+", a.get("href", "")):
                self.cell["link"] = a["href"]

    def handle_data(self, data):
        if not self.scope:
            return
        self.text_parts.append(data)
        if self.mode == "social" and self.title is not None:
            self.title["authors" if self.in_author else "title"].append(data)
        elif self.mode != "social" and self.cell is not None:
            self.cell["text"].append(data)

    def handle_endtag(self, tag):
        if self.scope:
            if self.mode == "social":
                if tag == "span" and self.in_author:
                    self.in_author = False
                if tag == "a" and self.title is not None and self.depth == self.title_depth:
                    self.articles.append(self.title)
                    self.title = None
            else:
                if tag == "td" and self.cell is not None and self.row is not None:
                    self.row.append(self.cell)
                    self.cell = None
                elif tag == "tr" and self.row is not None:
                    if len(self.row) == 1 and self.row[0]["link"]:
                        if self.awaiting_author:
                            raise ValueError("Article author row missing")
                        self.articles.append({"title": self.row[0]["text"], "url": self.row[0]["link"], "authors": []})
                        self.awaiting_author = True
                    elif self.awaiting_author:
                        if len(self.row) != 2:
                            raise ValueError("Article author row invalid")
                        self.articles[-1]["authors"] = self.row[1]["text"]
                        self.awaiting_author = False
                    self.row = None
            if tag == "div" and self.depth == self.scope:
                self.scope = 0
        if tag not in {"input", "img", "br", "meta", "link", "hr"}:
            self.depth = max(0, self.depth - 1)


def cass_current_toc(client, subscription, *, request, sleep):
    from .discovery import DiscoveryError

    issns = subscription.get("issns", [])
    if len(issns) != 1 or issns[0] not in JOURNALS:
        raise ValueError("Unknown CASS journal")
    name, host = JOURNALS[issns[0]]
    if subscription.get("name") != name:
        raise ValueError("Journal identity mismatch")
    url = f"https://{host}/"
    try:
        robots_response = request(client, url + "robots.txt", sleep=sleep)
    except DiscoveryError as exc:
        if str(exc) != "HTTP 404":
            raise
        robots_response = None  # RFC 9309: a 404 means no robots policy was published.
    if robots_response is not None:
        if robots_response.status_code != 200 or not re.search(r"(?im)^\s*user-agent\s*:", robots_response.text):
            raise ValueError("Unrecognized robots policy")
        rules = RobotFileParser()
        rules.parse(robots_response.text.splitlines())
        if not rules.can_fetch("Sociolit", url):
            raise ValueError("Publisher robots policy disallows access")
    response = request(client, url, sleep=sleep)
    if response.status_code != 200:
        raise ValueError("Official homepage unavailable")
    parser = CurrentIssueParser("social" if issns[0] == "1002-5936" else "population")
    parser.feed(response.text)
    if not parser.year:
        match = re.search(r"(20\d{2})\s*年\s*第\s*(\d+)\s*期", " ".join(parser.text_parts))
        if match:
            parser.year, parser.issue = match.groups()
    if not re.fullmatch(r"20\d{2}", parser.year) or not re.fullmatch(r"\d{1,2}", parser.issue) or not parser.articles:
        raise ValueError("Current issue structure changed or is empty")
    records, seen = [], set()
    for article in parser.articles:
        title = " ".join("".join(article["title"]).split())
        authors = [x.strip() for x in re.split(r"[、,，;；]", "".join(article["authors"])) if x.strip()]
        link = urljoin(url, article["url"])
        parts = urlsplit(link)
        if (parts.scheme != "https" or parts.hostname != host or parts.path != "/Magazine/Show"
                or not re.fullmatch(r"id=\d+", parts.query) or parts.fragment or link in seen
                or not title or title.endswith(("...", "…")) or not authors):
            raise ValueError("Incomplete or inconsistent article metadata")
        seen.add(link)
        records.append({"title": title, "authors": authors, "year": parser.year, "doi": "",
                        "journal": name, "url": link, "published_date": "", "sources": ["cass_current_toc"],
                        "source_ids": [link], "issns": issns})
    return records
