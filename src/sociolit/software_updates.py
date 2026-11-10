"""Public release checks and resumable, verified Windows installer downloads."""
import hashlib
import json
import math
import os
import re
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
from filelock import FileLock, Timeout

from .upgrades import _write

REPOSITORY = "Yoesher/SocioLibrary"
LATEST_URL = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
MAX_INSTALLER = 1536 * 1024 * 1024
CDN_HOSTS = {"release-assets.githubusercontent.com", "objects.githubusercontent.com", "github-releases.githubusercontent.com"}


class UpdateError(RuntimeError):
    pass


def version_tuple(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{1,6}\.\d{1,6}\.\d{1,6}", value):
        raise UpdateError("更新服务返回了无法识别的版本号。")
    return tuple(map(int, value.split(".")))


@dataclass(frozen=True)
class Release:
    version: str
    url: str
    digest: str
    size: int
    notes: str = ""


def validate_download_url(url, *, version, initial=False):
    try:
        parsed = urlparse(url)
        if (parsed.scheme != "https" or parsed.username or parsed.password or parsed.fragment
                or parsed.port not in (None, 443)):
            raise ValueError("Unsafe URL")
        if parsed.hostname == "github.com":
            name = f"SocioLibrary-{version}-Windows-x64-Setup.exe"
            if parsed.path != f"/{REPOSITORY}/releases/download/v{version}/{name}" or parsed.query:
                raise ValueError("Wrong repository or asset")
        elif initial or parsed.hostname not in CDN_HOSTS:
            raise ValueError("Unexpected download host")
    except (ValueError, TypeError) as exc:
        raise UpdateError("更新地址不属于本项目的官方发布来源，已拒绝下载。") from exc


def parse_release(payload, current_version):
    if not isinstance(payload, dict) or payload.get("draft") is not False or payload.get("prerelease") is not False:
        raise UpdateError("只接受官方正式版本，不安装草稿或预发布版本。")
    tag = payload.get("tag_name", "")
    if not isinstance(tag, str) or not tag.startswith("v"):
        raise UpdateError("正式版本标签无效。")
    version = tag[1:]
    if version_tuple(version) <= version_tuple(current_version):
        return None
    name = f"SocioLibrary-{version}-Windows-x64-Setup.exe"
    assets = payload.get("assets", [])
    if not isinstance(assets, list):
        raise UpdateError("更新文件列表无效。")
    found = [a for a in assets if isinstance(a, dict) and a.get("name") == name]
    if len(found) != 1:
        raise UpdateError("该版本尚未提供完整的 Windows 安装包，请稍后检查。")
    asset = found[0]
    digest = asset.get("digest", "")
    size = asset.get("size")
    if (not isinstance(digest, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest)
            or type(size) is not int or not 1024 * 1024 <= size <= MAX_INSTALLER
            or asset.get("state") != "uploaded"):
        raise UpdateError("更新包缺少有效校验值或大小信息，暂不安装。")
    url = asset.get("browser_download_url", "")
    validate_download_url(url, version=version, initial=True)
    notes = payload.get("body") or "此版本未填写更新说明。"
    if not isinstance(notes, str):
        raise UpdateError("版本说明格式无效。")
    return Release(version, url, digest.removeprefix("sha256:"), size, notes[:12000])


def client_factory():
    return httpx.Client(trust_env=False, follow_redirects=False,
                        timeout=httpx.Timeout(45, connect=15),
                        headers={"User-Agent": "SocioLibrary-Windows-Updater", "Accept-Encoding": "identity"})


def fetch_release(client, current_version):
    with client.stream("GET", LATEST_URL, headers={"Accept": "application/vnd.github+json",
                                                 "X-GitHub-Api-Version": "2022-11-28"}) as response:
        if response.status_code in (403, 429):
            raise UpdateError("更新服务暂时限制访问，请稍后再试；现有资料库可继续使用。")
        response.raise_for_status()
        body = bytearray()
        for block in response.iter_bytes():
            body.extend(block)
            if len(body) > 2 * 1024 * 1024:
                raise UpdateError("更新信息过长，已停止读取。")
    try:
        payload = json.loads(body)
    except ValueError as exc:
        raise UpdateError("更新服务未返回有效版本信息。") from exc
    return parse_release(payload, current_version)


def verify_installer(path, release):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size != release.size:
        raise UpdateError("更新包大小不符或尚未下载完成。")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        if stream.read(2) != b"MZ":
            raise UpdateError("下载内容不是 Windows 安装程序。")
        stream.seek(0)
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    if digest.hexdigest() != release.digest:
        raise UpdateError("更新包校验失败，已拒绝安装。请重新下载。")


def download_release(client, release, cache, progress=lambda *_: None):
    version_tuple(release.version)
    validate_download_url(release.url, version=release.version, initial=True)
    if not re.fullmatch(r"[0-9a-f]{64}", release.digest) or not 1024 * 1024 <= release.size <= MAX_INSTALLER:
        raise UpdateError("更新包校验信息无效。")
    folder = Path(cache) / (release.version + "-" + release.digest[:12])
    folder.mkdir(parents=True, exist_ok=True)
    try:
        with FileLock(str(folder / "download.lock"), timeout=0):
            return _download_locked(client, release, folder, progress)
    except Timeout as exc:
        raise UpdateError("另一个窗口正在下载此版本，请稍后重试。") from exc


def _mark_download(target, release):
    if os.name == "nt":
        try:
            Path(str(target) + ":Zone.Identifier").write_text("[ZoneTransfer]\nZoneId=3\nHostUrl=" + release.url, encoding="utf-8")
        except OSError:
            pass  # Some local filesystems do not support NTFS alternate streams.
    return target


def _download_locked(client, release, folder, progress):
    target = folder / f"SocioLibrary-{release.version}-Windows-x64-Setup.exe"
    partial = target.with_suffix(".exe.part")
    if target.exists():
        try:
            verify_installer(target, release)
            progress(release.size, release.size)
            return _mark_download(target, release)
        except UpdateError:
            if target.is_symlink():
                raise
            target.unlink()
    if partial.is_symlink():
        raise UpdateError("更新缓存路径异常，请检查本机缓存。")
    offset = partial.stat().st_size if partial.exists() else 0
    if offset > release.size:
        partial.unlink()
        offset = 0
    if offset == release.size:
        try:
            verify_installer(partial, release)
        except UpdateError:
            partial.unlink()
            raise
        os.replace(partial, target)
        progress(release.size, release.size)
        return _mark_download(target, release)
    headers = {"Range": f"bytes={offset}-"} if offset else {}
    url = release.url
    for redirect in range(6):
        validate_download_url(url, version=release.version, initial=redirect == 0)
        with client.stream("GET", url, headers=headers) as response:
            if response.status_code in (301, 302, 303, 307, 308):
                url = urljoin(url, response.headers.get("location", ""))
                continue
            response.raise_for_status()
            if response.status_code not in (200, 206) or response.headers.get("content-encoding", "identity") != "identity":
                raise UpdateError("更新下载响应异常，已停止。")
            if response.status_code == 206:
                match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", response.headers.get("content-range", ""))
                if not match or tuple(map(int, match.groups())) != (offset, release.size - 1, release.size):
                    raise UpdateError("更新包续传范围不符，已停止下载。")
            else:
                offset = 0
            length = response.headers.get("content-length")
            if length is not None and length != str(release.size - offset):
                raise UpdateError("更新包长度与官方发布记录不符。")
            downloaded = offset
            progress(downloaded, release.size)
            with partial.open("ab" if offset else "wb") as output:
                for block in response.iter_bytes(256 * 1024):
                    downloaded += len(block)
                    if downloaded > release.size:
                        raise UpdateError("更新包超过预期大小，已停止下载。")
                    output.write(block)
                    progress(downloaded, release.size)
            if downloaded != release.size:
                raise UpdateError("下载尚未完成，重试时会继续已有进度。")
            break
    else:
        raise UpdateError("更新下载跳转次数过多，已停止。")
    try:
        verify_installer(partial, release)
    except UpdateError:
        partial.unlink(missing_ok=True)
        raise
    os.replace(partial, target)
    return _mark_download(target, release)


class UpdateManager:
    def __init__(self, directory, version, *, cache=None, factory=client_factory):
        self._directory = Path(directory)
        self._path = self._directory / "software-update.json"
        self._version = version
        self._cache = Path(cache) if cache else Path(os.environ.get("LOCALAPPDATA", self._directory.parent)) / "SocioLibrary/updates"
        self._factory = factory
        self._lock = threading.RLock()
        self._settings = {"auto_check": True, "last_attempt": 0, "last_checked": 0}
        self._state, self._error, self._release, self._ready = "idle", "", None, None
        self._downloaded, self._total = 0, 0
        self._thread = None
        if self._path.is_file():
            try:
                saved = json.loads(self._path.read_text(encoding="utf-8"))
                if not isinstance(saved, dict) or type(saved.get("auto_check", True)) is not bool:
                    raise ValueError("Invalid settings")
                for key in ("last_attempt", "last_checked"):
                    value = saved.get(key, 0)
                    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                        raise ValueError("Invalid check timestamp")
                self._settings.update({key: saved[key] for key in self._settings if key in saved})
                if saved.get("release"):
                    data = saved["release"]
                    self._release = parse_release({"tag_name": "v" + data["version"], "draft": False, "prerelease": False,
                        "body": data.get("notes", ""), "assets": [{"name": f"SocioLibrary-{data['version']}-Windows-x64-Setup.exe",
                        "size": data["size"], "digest": "sha256:" + data["digest"], "state": "uploaded",
                        "browser_download_url": data["url"]}]}, version)
                    self._state = "available" if self._release else "current"
            except (OSError, ValueError, TypeError, KeyError, UpdateError):
                self._settings = {"auto_check": False, "last_attempt": 0, "last_checked": 0}
                self._state, self._error = "error", "更新设置无法读取；资料库仍可使用，可手动重新检查更新。"

    def snapshot(self):
        with self._lock:
            return {"state": self._state, "error": self._error, "auto_check": self._settings["auto_check"],
                    "current_version": self._version, "available_version": self._release.version if self._release else "",
                    "notes": self._release.notes if self._release else "", "last_checked": self._settings["last_checked"],
                    "downloaded": self._downloaded, "total": self._total}

    def _persist(self):
        _write(self._path, dict(self._settings, release=asdict(self._release) if self._release else None))

    def set_automatic(self, enabled):
        if type(enabled) is not bool:
            raise UpdateError("自动检查选项无效。")
        with self._lock:
            self._settings["auto_check"] = enabled
            self._persist()
        return self.snapshot()

    def _start(self, state, action):
        with self._lock:
            if self._thread and self._thread.is_alive():
                raise UpdateError("更新任务正在进行，请等待当前任务结束。")
            self._state, self._error = state, ""
            def run():
                try:
                    action()
                except Exception as exc:
                    with self._lock:
                        self._state = "error"
                        self._error = str(exc) if isinstance(exc, UpdateError) else "连接或下载更新失败，请稍后重试；现有资料不受影响。"
            self._thread = threading.Thread(target=run, daemon=True)
            self._thread.start()
        return self.snapshot()

    def check(self, *, automatic=False):
        with self._lock:
            now = time.time()
            try:
                elapsed = now - float(self._settings["last_attempt"])
                checked_elapsed = now - float(self._settings["last_checked"])
            except (ValueError, TypeError):
                elapsed = checked_elapsed = 86401
            if automatic and (not self._settings["auto_check"] or 0 <= elapsed < 3600 or 0 <= checked_elapsed < 86400):
                return self.snapshot()
        def run():
            with self._lock:
                self._settings["last_attempt"] = time.time()
                self._persist()
            with self._factory() as client:
                release = fetch_release(client, self._version)
            with self._lock:
                self._release, self._ready = release, None
                self._downloaded = self._total = 0
                self._settings["last_checked"] = time.time()
                self._persist()
                self._state = "available" if release else "current"
        return self._start("checking", run)

    def download(self):
        with self._lock:
            release = self._release
            if release is None:
                raise UpdateError("请先检查并找到可用的新版本。")
        def progress(done, total):
            with self._lock:
                self._downloaded, self._total = done, total
        def run():
            for attempt in range(3):
                try:
                    with self._factory() as client:
                        ready = download_release(client, release, self._cache, progress)
                    break
                except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                    if attempt == 2 or isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code < 500:
                        raise
                    time.sleep(attempt + 1)
            with self._lock:
                self._ready, self._state = ready, "ready"
        return self._start("downloading", run)

    def ready_installer(self):
        with self._lock:
            if self._state != "ready" or not self._ready or not self._release:
                raise UpdateError("更新包尚未完成下载和校验。")
            release, path = self._release, self._ready
        if version_tuple(release.version) <= version_tuple(self._version):
            raise UpdateError("不会安装当前版本或更旧的版本。")
        verify_installer(path, release)
        return release, path
