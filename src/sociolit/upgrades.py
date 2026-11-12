"""Local upgrade snapshots; installers never own research data."""
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import time
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


class UpgradeError(RuntimeError):
    pass


class UpgradeCancelled(UpgradeError):
    """A user cancelled before the new version was initialized."""


def _version(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d+\.\d+\.\d+", value):
        raise UpgradeError("软件版本记录无效，请保留资料目录并联系维护者。")
    return tuple(map(int, value.split(".")))


def _read(path):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("Not an object")
        return value
    except (OSError, ValueError) as exc:
        raise UpgradeError("本机升级记录无法读取，已停止初始化，请保留原资料。") from exc


def _write(path, value):
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temp.open('w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        # Windows scanners can briefly hold the destination after a settings read.
        # Retry only sharing/access contention; never delete the previous file.
        for attempt in range(6):
            try:
                os.replace(temp, path)
                break
            except PermissionError:
                if attempt == 5:
                    raise
                time.sleep(.025 * (attempt + 1))
    finally:
        temp.unlink(missing_ok=True)


def resolve_desktop_directory(explicit=None):
    """An explicit folder or environment override wins over the remembered folder."""
    from .config import default_data_dir

    if explicit or os.environ.get("SOCIOLIT_DATA_DIR"):
        return physical_directory(Path(explicit).expanduser() if explicit else default_data_dir())
    pointer = location_file()
    if not pointer.is_file():
        pointer = legacy_location_file()
    if pointer.is_file():
        value = _read(pointer).get("data_dir")
        if (not isinstance(value, str) or not Path(value).is_absolute() or not Path(value).is_dir()
                or not (Path(value) / "library.sqlite3").is_file()):
            raise UpgradeError("之前的资料目录暂时不可用，请先连接原磁盘；不会自动创建空库替代。")
        return physical_directory(Path(value))
    return physical_directory(default_data_dir())


def location_file():
    # AppData can be virtualized by a packaged launcher. The shared pointer must
    # be visible to normal Explorer launches and launcher child processes alike.
    if sys.platform == 'win32':
        return Path.home() / '.sociolibrary' / 'desktop-location.json'
    return legacy_location_file()


def legacy_location_file():
    from .config import default_data_dir

    base = Path(os.environ.get("LOCALAPPDATA", default_data_dir().parent))
    return base / "SocioLibrary" / "desktop-location.json"


def physical_directory(directory):
    directory = Path(directory)
    database = directory / 'library.sqlite3'
    # Resolve the existing file, not its overlaid directory: on MSIX Windows
    # those can point to different physical locations. Never move or merge data.
    return database.resolve(strict=True).parent if database.is_file() else directory.resolve()


def remember_directory(directory):
    path = location_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    _write(path, {"data_dir": str(physical_directory(directory))})


def prepare_upgrade(directory, version, progress=None):
    """Call while holding library.lock, before Store or schema initialization."""
    directory = Path(directory)
    notify = progress or (lambda *_: None)
    notify("检查资料版本", None)
    marker = directory / "desktop-version.json"
    previous = _read(marker) if marker.exists() else {}
    current = _version(version)
    old = previous.get("version")
    if old is not None and _version(old) > current:
        raise UpgradeError("这份资料已由更新版本打开，请使用相同或更新的软件版本，避免降级损坏资料。")
    database = directory / "library.sqlite3"
    if not database.is_file() and (marker.exists() or (directory / "preferences.json").exists()
                                   or (directory / "models").exists()):
        raise UpgradeError("发现原资料的设置，但数据库文件缺失，已停止创建空库。请连接原磁盘或从备份恢复。")
    if old == version:
        return previous
    report = {"version": version, "previous_version": old or "legacy", "inherited": False, "backup": ""}
    if not database.exists():
        return report
    report["inherited"] = True
    estimate = database.stat().st_size
    wal = database.with_name(database.name + "-wal")
    if wal.is_file():
        estimate += wal.stat().st_size
    if shutil.disk_usage(directory).free < estimate + 64 * 1024 * 1024:
        raise UpgradeError("升级前备份所需磁盘空间不足，原库未修改。请释放空间后重新启动。")
    backups = directory / "backups"
    backups.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = backups / f"{stamp}-to-{version}-{uuid.uuid4().hex[:8]}"
    started = time.monotonic()

    def check_deadline():
        if time.monotonic() - started > 600:
            raise UpgradeError("升级前备份或校验超时，原库未修改。请关闭其他写入任务后重试。")

    def check_progress(_status, remaining, total):
        check_deadline()
        notify("备份原资料", int(100 * (total - remaining) / total) if total else 0)

    try:
        notify("备份原资料", 0)
        with tempfile.TemporaryDirectory(prefix=".upgrade-", dir=backups) as temp:
            staging = Path(temp)
            with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as source:
                tables = {r[0] for r in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if not {"items", "files", "chunks", "chunks_fts", "vectors", "state"} <= tables:
                    raise UpgradeError("原数据库未被识别为 SocioLibrary 资料库，已停止初始化；不会向其他数据库写入。")
                with closing(sqlite3.connect(staging / "library.sqlite3")) as target:
                    source.backup(target, pages=256, progress=check_progress, sleep=0.05)
                    notify("校验备份 · 大库可能需要数分钟", None)
                    interrupted = None

                    def validation_progress():
                        nonlocal interrupted
                        try:
                            check_deadline()
                            notify("校验备份 · 大库可能需要数分钟", None)
                            return 0
                        except UpgradeError as exc:
                            interrupted = exc
                            return 1

                    target.set_progress_handler(validation_progress, 10000)
                    try:
                        result = target.execute("PRAGMA quick_check").fetchall()
                    except sqlite3.Error as exc:
                        if interrupted:
                            raise interrupted from exc
                        raise
                    finally:
                        target.set_progress_handler(None, 0)
                    if result != [("ok",)]:
                        raise UpgradeError("升级备份校验失败，原库未修改，请保留资料并联系维护者。")
            notify("保存升级备份", None)
            for name in ("preferences.json", "desktop-version.json", "software-update.json", "ai-profiles.json"):
                path = directory / name
                if path.exists():
                    shutil.copy2(path, staging / name)
            report["backup"] = str(destination.relative_to(directory))
            (staging / "manifest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            staging.rename(destination)
    except UpgradeError:
        raise
    except (OSError, sqlite3.Error) as exc:
        raise UpgradeError("无法完成升级前备份，原库未修改。请检查磁盘空间、文件权限及本机日志后重试。") from exc
    return report


def complete_upgrade(directory, report):
    """Only record the new version after database and preferences load successfully."""
    _write(Path(directory) / "desktop-version.json", report)


def upgrade_status(directory):
    marker = Path(directory) / "desktop-version.json"
    if not marker.is_file():
        return {}
    try:
        report = _read(marker)
        backup = Path(directory) / report.get("backup", "")
        return {"inherited": bool(report.get("inherited")), "previous_version": report.get("previous_version"),
                "backup_ready": bool(report.get("backup")) and (backup / "manifest.json").is_file()}
    except UpgradeError:
        return {}
