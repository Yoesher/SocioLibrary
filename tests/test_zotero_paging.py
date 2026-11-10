import httpx
import pytest

from sociolit.zotero import ZoteroClient, ZoteroError


def fake_items(start, size):
    return [{"key": f"{i:08X}", "data": {"key": f"{i:08X}", "itemType": "journalArticle", "title": "synthetic"}}
            for i in range(start, start + size)]


@pytest.mark.parametrize("change", ["none", "page", "final", "duplicate"])
def test_paged_library_only_commits_a_complete_stable_version(change):
    def handler(request):
        params = request.url.params
        final = params.get("format") == "versions"
        start = int(params.get("start", 0))
        version = "2" if (change == "page" and start == 100) or (change == "final" and final) else "1"
        headers = {"Zotero-Server-ID": "server1", "Last-Modified-Version": version, "Total-Results": "101"}
        if final:
            return httpx.Response(200, json={}, headers=headers)
        if start == 0:
            headers["Link"] = '<http://127.0.0.1:23119/api/users/0/items?start=100>; rel="next"'
            return httpx.Response(200, json=fake_items(0, 100), headers=headers)
        assert request.headers["Zotero-Server-ID"] == "server1"
        return httpx.Response(200, json=fake_items(0 if change == "duplicate" else 100, 1), headers=headers)

    with ZoteroClient(transport=httpx.MockTransport(handler)) as client:
        if change == "none":
            snapshot = client.snapshot()
            assert snapshot.complete and len(snapshot.items) == 101
        else:
            with pytest.raises(ZoteroError):
                client.snapshot()


def test_old_api_retries_unpaged_instead_of_unsafe_pagination():
    calls = []
    def handler(request):
        calls.append(str(request.url))
        if len(calls) == 1:
            return httpx.Response(200, json=fake_items(0, 1), headers={"Total-Results": "2", "Link": '<x>; rel="next"'})
        return httpx.Response(200, json=fake_items(0, 2), headers={"Total-Results": "2"})
    with ZoteroClient(transport=httpx.MockTransport(handler)) as client:
        snapshot = client.snapshot()
    assert len(calls) == 2 and len(snapshot.items) == 2 and "limit=" not in calls[1]


def test_collection_list_requires_complete_and_valid_metadata():
    records = [{"key":"AAAA1111", "data":{"key":"AAAA1111", "name":"生育", "parentCollection":False}},
               {"key":"BBBB2222", "data":{"key":"BBBB2222", "name":"家庭", "parentCollection":"AAAA1111"}}]
    def handler(request):
        return httpx.Response(200, json=records, headers={"Total-Results":"2", "Zotero-Server-ID":"source"})
    with ZoteroClient(transport=httpx.MockTransport(handler)) as client:
        source, collections = client.collections()
    assert source == "zotero:source" and collections[1]["parent"] == "AAAA1111"
    for headers in ({"Total-Results":"3"}, {"Link":'<x>; rel="next"'}):
        with ZoteroClient(transport=httpx.MockTransport(lambda request, h=headers: httpx.Response(200, json=records, headers=h))) as client:
            with pytest.raises(ZoteroError):
                client.collections()
