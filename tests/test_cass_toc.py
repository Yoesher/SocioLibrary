from datetime import date

import httpx
import pytest

from sociolit.discovery import run_discovery

SOCIAL = {"name": "社会学研究", "issns": ["1002-5936"], "enabled": True, "sources": ["cass_current_toc"]}
POP = {"name": "中国人口科学", "issns": ["1000-7881"], "enabled": True, "sources": ["cass_current_toc"]}
SOCIAL_HTML = '''<input id="iYear" value="2026"><input id="iIsue" value="5">
<div id="IssueList"><div class="article"><p><a id="a 42" href="/Magazine/Show?id=42">合成标题<span>作者甲、作者乙</span></a></p></div></div>'''
POP_HTML = '''<div class="qk"><p>期刊目录 2026年第5期</p><table><tr><td><a href="/Magazine/Show?id=42"><b>合成标题</b></a></td></tr><tr><td></td><td>作者甲；作者乙</td></tr><tr><td></td><td>摘要 secret text</td></tr></table></div>'''


def check(sub, page, robots=404):
    calls = []
    def handler(request):
        calls.append(str(request.url))
        if request.url.path == "/robots.txt":
            return httpx.Response(robots, text="User-agent: *\nDisallow: /" if robots == 200 else "not found")
        return httpx.Response(200, text=page)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = run_discovery([sub], date(2026, 8, 1), date(2026, 11, 7), client=client, sleep=lambda _: None)
    return result, calls


@pytest.mark.parametrize(("subscription", "page"), [(SOCIAL, SOCIAL_HTML), (POP, POP_HTML)])
def test_current_snapshot_extracts_metadata_only(subscription, page):
    result, calls = check(subscription, page)
    assert result.complete and len(result.records) == 1
    assert result.records[0]["title"] == "合成标题"
    assert result.records[0]["authors"] == ["作者甲", "作者乙"]
    assert result.records[0]["published_date"] == ""
    assert "secret text" not in str(result.records)
    assert len(calls) == 2
    assert any("仅检查官网当前一期" in warning for warning in result.warnings)


def test_robots_disallow_and_unavailable_not_404_stop_access():
    for status in (200, 403):
        result, calls = check(SOCIAL, SOCIAL_HTML, status)
        assert not result.complete and len(calls) == 1


@pytest.mark.parametrize("page", ["<html>bad</html>", SOCIAL_HTML.replace("合成标题", "截断..."), SOCIAL_HTML.replace("作者甲、作者乙", "")])
def test_incomplete_metadata_does_not_advance(page):
    result, _ = check(SOCIAL, page)
    assert not result.complete and not result.records


def test_missing_author_cannot_be_replaced_by_following_abstract():
    result, _ = check(POP, POP_HTML.replace("作者甲；作者乙", ""))
    assert not result.complete and not result.records
