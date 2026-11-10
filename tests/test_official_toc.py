from datetime import date

import httpx

from sociolit.discovery import run_discovery

SUB = {"name": "人口研究", "issns": ["1000-6087"], "enabled": True, "sources": ["official_toc"]}
HOST = "https://rkyj.ruc.edu.cn"
CURRENT = HOST + "/CN/1000-6087/current.shtml"
PREVIOUS = HOST + "/CN/volumn/volumn_10.shtml"


def issue(number=5, published="2026-09-29", title="合成论文题名", previous="../volumn/volumn_10.shtml"):
    return f'''<html><div class="njq">2026年 第50卷 第{number}期 刊出日期：{published}</div>
    <a href="{previous}">上一期</a><form id="AbstractList"><div id="art123" class="noselectrow">
    <a class="biaoti" href="{HOST}/CN/Y2026/V50/I{number}/3">{title}</a>
    <dd class="zuozhe">合成作者甲, 合成作者乙</dd><div class="zhaiyao">private abstract not saved</div>
    </div></form></html>'''


def check(handler, subscription=SUB, since=date(2026, 8, 1), max_pages=20):
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        return run_discovery([subscription], since, date(2026, 11, 7), client=client,
                             sleep=lambda _: None, max_pages=max_pages)


def test_current_and_previous_issue_backfill_without_abstract():
    requests = []
    def handler(request):
        url = str(request.url)
        requests.append(url)
        if url.endswith("/robots.txt"):
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        if url == CURRENT:
            return httpx.Response(200, text=issue())
        if url == PREVIOUS:
            return httpx.Response(200, text=issue(4, "2026-07-29", "另一合成论文"))
        raise AssertionError(url)
    result = check(handler)
    assert result.complete and len(result.records) == 2
    assert result.records[0]["sources"] == ["official_toc"]
    assert result.records[0]["authors"] == ["合成作者甲", "合成作者乙"]
    assert "private abstract" not in str(result.records)
    assert requests == [HOST + "/robots.txt", CURRENT, PREVIOUS]


def test_rejects_robots_disallow_and_html_error_pages():
    for robots in ("User-agent: *\nDisallow: /\n", "<html>error</html>"):
        calls = []
        def handler(request, calls=calls, robots=robots):
            calls.append(str(request.url))
            return httpx.Response(200, text=robots)
        result = check(handler)
        assert not result.complete and not result.records
        assert len(calls) == 1


def test_incomplete_issue_or_external_redirects_are_errors():
    for page in ("<html>not an issue</html>", issue(title="截断的论文..."),
                 issue(previous="https://example.org/CN/volumn/volumn_10.shtml")):
        result = check(lambda request, page=page: httpx.Response(200, text="User-agent: *\nAllow: /" if request.url.path == "/robots.txt" else page))
        assert not result.complete and not result.records


def test_missing_previous_and_page_cap_are_not_reported_as_success():
    for page, cap in ((issue(previous=""), 20), (issue(), 1)):
        result = check(lambda request, page=page: httpx.Response(200, text="User-agent: *\nAllow: /" if request.url.path == "/robots.txt" else page), max_pages=cap)
        assert not result.complete and not result.records


def test_wrong_journal_cannot_use_fixed_host():
    result = check(lambda request: httpx.Response(200, text="unused"), subscription={**SUB, "name": "other"})
    assert not result.complete
