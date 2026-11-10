import copy
import hashlib
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from sociolit.server import create_app
from sociolit.software_updates import (
    LATEST_URL,
    UpdateError,
    UpdateManager,
    download_release,
    parse_release,
    verify_installer,
)
from sociolit.store import Store

DATA = b"MZ" + b"synthetic" * 120000
DIGEST = hashlib.sha256(DATA).hexdigest()
NAME = "SocioLibrary-0.4.1-Windows-x64-Setup.exe"
URL = "https://github.com/Yoesher/SocioLibrary/releases/download/v0.4.1/" + NAME
CDN = "https://release-assets.githubusercontent.com/synthetic-installer"


def metadata():
    return {
        "tag_name": "v0.4.1",
        "draft": False,
        "prerelease": False,
        "body": "合成版本说明",
        "assets": [
            {
                "name": NAME,
                "state": "uploaded",
                "size": len(DATA),
                "digest": "sha256:" + DIGEST,
                "browser_download_url": URL,
            }
        ],
    }


def finished(manager):
    manager._thread.join(5)
    assert not manager._thread.is_alive()
    return manager.snapshot()


@pytest.mark.parametrize(
    "fault",
    ["prerelease", "draft", "foreign_repository", "missing_digest", "duplicate", "oversize", "wrong_tag"],
)
def test_rejects_untrusted_or_incomplete_release_descriptors(fault):
    payload = metadata()
    if fault in ("prerelease", "draft"):
        payload[fault] = True
    elif fault == "foreign_repository":
        payload["assets"][0]["browser_download_url"] = URL.replace("Yoesher", "someone-else")
    elif fault == "missing_digest":
        del payload["assets"][0]["digest"]
    elif fault == "duplicate":
        payload["assets"].append(copy.deepcopy(payload["assets"][0]))
    elif fault == "oversize":
        payload["assets"][0]["size"] = 2**40
    else:
        payload["tag_name"] = "v0.4.1-rc1"
    with pytest.raises(UpdateError):
        parse_release(payload, "0.4.0")


def test_no_downgrade_or_same_version_and_correct_numeric_version_order():
    assert parse_release(metadata(), "0.4.1") is None
    assert parse_release(metadata(), "0.5.0") is None
    assert parse_release(metadata(), "0.3.99").version == "0.4.1"


def test_resumes_partial_download_through_official_redirect_and_reuses_verified_cache(tmp_path):
    release = parse_release(metadata(), "0.4.0")
    folder = tmp_path / (release.version + "-" + DIGEST[:12])
    folder.mkdir()
    partial = folder / (NAME + ".part")
    partial.write_bytes(DATA[:300000])
    requests, progress = [], []

    def respond(request):
        requests.append(str(request.url))
        assert request.headers["range"] == "bytes=300000-"
        if str(request.url) == URL:
            return httpx.Response(302, headers={"Location": CDN})
        return httpx.Response(
            206, headers={"Content-Range": f"bytes 300000-{len(DATA) - 1}/{len(DATA)}"}, content=DATA[300000:]
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        path = download_release(client, release, tmp_path, lambda a, b: progress.append((a, b)))
        verify_installer(path, release)
        assert path.read_bytes() == DATA and not partial.exists()
        assert download_release(client, release, tmp_path) == path
    assert requests == [URL, CDN] and progress[-1] == (len(DATA), len(DATA))


def test_server_ignoring_range_restarts_download_instead_of_appending(tmp_path):
    release = parse_release(metadata(), "0.4.0")
    folder = tmp_path / (release.version + "-" + DIGEST[:12])
    folder.mkdir()
    (folder / (NAME + ".part")).write_bytes(DATA[:100])
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, content=DATA))) as client:
        assert download_release(client, release, tmp_path).read_bytes() == DATA


@pytest.mark.parametrize(
    "destination",
    [
        "http://release-assets.githubusercontent.com/unsafe",
        "https://evil.example/installer.exe",
        "https://github.com/other/repository/releases/download/v1.0.0/file.exe",
    ],
)
def test_redirect_cannot_escape_official_https_release_hosts(tmp_path, destination):
    visited = []

    def respond(request):
        visited.append(str(request.url))
        return httpx.Response(302, headers={"Location": destination})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(UpdateError):
            download_release(client, parse_release(metadata(), "0.4.0"), tmp_path)
    assert visited == [URL]
    assert not list(tmp_path.rglob("*.exe"))


def test_corrupt_download_is_never_ready_and_is_not_executed(tmp_path):
    payload = metadata()
    payload["assets"][0]["digest"] = "sha256:" + "0" * 64
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, content=DATA))) as client:
        with pytest.raises(UpdateError, match="校验失败"):
            download_release(client, parse_release(payload, "0.4.0"), tmp_path)
    assert not list(tmp_path.rglob("*.exe")) and not list(tmp_path.rglob("*.part"))


def test_invalid_range_keeps_existing_partial_and_short_response_is_not_ready(tmp_path):
    release = parse_release(metadata(), "0.4.0")
    folder = tmp_path / (release.version + "-" + DIGEST[:12])
    folder.mkdir()
    partial = folder / (NAME + ".part")
    partial.write_bytes(DATA[:100])
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                206, headers={"Content-Range": f"bytes 0-{len(DATA) - 1}/{len(DATA)}"}, content=DATA
            )
        )
    ) as client:
        with pytest.raises(UpdateError, match="续传范围"):
            download_release(client, release, tmp_path)
    assert partial.read_bytes() == DATA[:100]
    partial.unlink()
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=DATA[:300000]))
    ) as client:
        with pytest.raises(UpdateError, match="长度"):
            download_release(client, release, tmp_path)


def test_manager_daily_check_preferences_and_verified_download_survive_restart(tmp_path):
    seen = []

    def respond(request):
        seen.append(str(request.url))
        assert not request.content and "authorization" not in request.headers
        return (
            httpx.Response(200, json=metadata())
            if str(request.url) == LATEST_URL
            else httpx.Response(200, content=DATA)
        )

    def factory():
        return httpx.Client(transport=httpx.MockTransport(respond))

    manager = UpdateManager(tmp_path, "0.4.0", cache=tmp_path / "cache", factory=factory)
    manager.check(automatic=True)
    assert finished(manager)["state"] == "available"
    manager.check(automatic=True)
    assert seen == [LATEST_URL]
    manager.set_automatic(False)
    resumed = UpdateManager(tmp_path, "0.4.0", cache=tmp_path / "cache", factory=factory)
    resumed.check(automatic=True)
    assert seen == [LATEST_URL] and not resumed.snapshot()["auto_check"]
    resumed.download()
    assert finished(resumed)["state"] == "ready"
    release, path = resumed.ready_installer()
    assert path.read_bytes() == DATA and release.version == "0.4.1"
    upgraded = UpdateManager(tmp_path, "0.4.1", factory=factory)
    assert not upgraded.snapshot()["available_version"]
    with pytest.raises(UpdateError):
        upgraded.download()


def test_optional_update_settings_failure_does_not_break_library_and_errors_back_off(tmp_path):
    (tmp_path / "software-update.json").write_text("broken synthetic settings", encoding="utf-8")
    calls = []

    def offline(request):
        calls.append(str(request.url))
        raise httpx.ConnectError("Synthetic offline", request=request)

    manager = UpdateManager(
        tmp_path, "0.4.0", factory=lambda: httpx.Client(transport=httpx.MockTransport(offline))
    )
    assert manager.snapshot()["state"] == "error" and not manager.snapshot()["auto_check"]
    manager.set_automatic(True)
    manager.check()
    assert finished(manager)["state"] == "error"
    manager.check(automatic=True)
    assert calls == [LATEST_URL]


def test_update_and_research_routes_require_local_token_and_installation_is_native_only(tmp_path):
    store = Store(tmp_path)
    app = create_app(store, {})
    with TestClient(app, base_url="http://localhost") as client:
        for path in (
            "/api/software-update/check",
            "/api/software-update/download",
            "/api/research/recent/clear",
        ):
            assert client.post(path).status_code == 403
        assert client.get("/api/research/reading").status_code == 403
        headers = {"X-Sociolit-Token": client.get("/api/status").json()["token"]}
        assert client.post("/api/software-update/install", headers=headers).status_code == 404
        app.state.maintenance.set()
        assert (
            client.post(
                "/api/research/notes",
                headers=headers,
                json={"title": "Synthetic", "body": "not saved during installation"},
            ).status_code
            == 409
        )
        assert client.get("/api/research", headers=headers).status_code == 200


def test_checks_are_background_work_and_reject_overlapping_downloads(tmp_path):
    import threading

    entered, release = threading.Event(), threading.Event()

    def slow(request):
        entered.set()
        assert release.wait(3)
        return httpx.Response(200, json=metadata())

    manager = UpdateManager(
        tmp_path, "0.4.0", factory=lambda: httpx.Client(transport=httpx.MockTransport(slow))
    )
    start = time.monotonic()
    manager.check()
    assert time.monotonic() - start < 1 and entered.wait(1)
    with pytest.raises(UpdateError, match="正在进行"):
        manager.check()
    release.set()
    assert finished(manager)["state"] == "available"


def test_transient_stream_failure_resumes_automatically_without_restarting_the_whole_download(tmp_path):
    class Interrupted(httpx.SyncByteStream):
        def __iter__(self):
            yield DATA[:300000]
            raise httpx.ReadError("Synthetic interrupted connection")

    ranges = []

    def respond(request):
        if str(request.url) == LATEST_URL:
            return httpx.Response(200, json=metadata())
        ranges.append(request.headers.get("range"))
        if len(ranges) == 1:
            return httpx.Response(200, headers={"Content-Length": str(len(DATA))}, stream=Interrupted())
        offset = int(request.headers["range"].removeprefix("bytes=").removesuffix("-"))
        assert offset > 0
        return httpx.Response(
            206,
            headers={"Content-Range": f"bytes {offset}-{len(DATA) - 1}/{len(DATA)}"},
            content=DATA[offset:],
        )

    manager = UpdateManager(
        tmp_path,
        "0.4.0",
        cache=tmp_path / "cache",
        factory=lambda: httpx.Client(transport=httpx.MockTransport(respond)),
    )
    manager.check()
    finished(manager)
    manager.download()
    assert finished(manager)["state"] == "ready"
    assert manager.ready_installer()[1].read_bytes() == DATA and len(ranges) == 2


def test_nonfinite_cached_timestamp_never_breaks_library_status(tmp_path):
    (tmp_path / "software-update.json").write_text('{"auto_check":true,"last_checked":NaN}', encoding="utf-8")
    with TestClient(create_app(Store(tmp_path), {}), base_url="http://localhost") as client:
        response = client.get("/api/status")
        assert response.status_code == 200
        assert response.json()["software_update"]["state"] == "error"


def test_shared_cache_download_lock_prevents_competing_windows(tmp_path):
    from filelock import FileLock

    release = parse_release(metadata(), "0.4.0")
    folder = tmp_path / (release.version + "-" + DIGEST[:12])
    folder.mkdir()
    with FileLock(str(folder / "download.lock")):
        with httpx.Client(
            transport=httpx.MockTransport(lambda _: pytest.fail("No network while cache is locked"))
        ) as client:
            with pytest.raises(UpdateError, match="另一个窗口"):
                download_release(client, release, tmp_path)


def test_desktop_install_refuses_to_close_during_a_background_library_job(tmp_path, monkeypatch):
    import threading

    from sociolit.desktop import DesktopAPI

    entered, finish = threading.Event(), threading.Event()
    app = create_app(Store(tmp_path), {})

    def work(_):
        entered.set()
        assert finish.wait(3)

    app.state.jobs.start("synthetic", work)
    assert entered.wait(1)
    monkeypatch.setattr("sociolit.update_install.native_install_context", lambda: {"supported": True})
    bridge = DesktopAPI()
    bridge._native_lock = threading.Lock()
    bridge._app = app
    try:
        with pytest.raises(UpdateError, match="任务完成"):
            bridge.install_update()
        assert not app.state.maintenance.is_set()
    finally:
        finish.set()
