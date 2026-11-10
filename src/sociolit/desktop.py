"""Windows desktop entry point. Installer data and research data are separate."""
import argparse
import ctypes
import json
import logging
import os
import socket
import sys
import threading
import time
from pathlib import Path

import httpx
import uvicorn
from filelock import FileLock, Timeout

from . import __version__
from .config import read_config
from .server import create_app
from .store import Store
from .upgrades import (
    UpgradeError,
    complete_upgrade,
    prepare_upgrade,
    remember_directory,
    resolve_desktop_directory,
)


def base_config():
    bundled = Path(__file__).parent / "defaults" / "public-journals.toml"
    source = Path(__file__).resolve().parents[2] / "config" / "public-journals.toml"
    return read_config(bundled if bundled.is_file() else source)


def message(text):
    ctypes.windll.user32.MessageBoxW(None, text, "SocioLibrary", 0x40)


def installer_mutex():
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.CreateMutexW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.CreateMutexW(None, False, "SocioLibraryDesktop")
    if not handle:
        raise OSError(ctypes.get_last_error(), "Cannot protect the running application from replacement")
    return kernel, handle


def initialize_desktop_library(directory):
    """Snapshot the old database before any current-version schema initialization."""
    try:
        with FileLock(str(directory / "library.lock"), timeout=1):
            report = prepare_upgrade(directory, __version__)
            config = base_config()
            store = Store(directory)
            if not (directory / "preferences.json").exists():
                previous_scope = store.state("semantic_scope")
                if isinstance(previous_scope, dict) and previous_scope.get("label"):
                    config.setdefault("semantic", {})["collection_keywords"] = previous_scope["label"].split("、")
            app = create_app(store, config)
            complete_upgrade(directory, report)
            return store, config, app
    except Timeout as exc:
        raise UpgradeError("原资料库正在被其他任务使用，请等待同步或索引结束后重新启动。") from exc


class DesktopAPI:
    def choose_folder(self):
        import webview
        result = self._window.create_file_dialog(webview.FOLDER_DIALOG)
        return result[0] if result else None

    def open_data_folder(self):
        os.startfile(str(self._directory))
        return True

    def open_releases(self):
        import webbrowser
        webbrowser.open("https://github.com/Yoesher/SocioLibrary/releases")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument("--data-dir")
    parser.add_argument("--update-journals", action="store_true")
    args = parser.parse_args()
    if sys.platform != "win32":
        raise SystemExit("Desktop distribution currently supports Windows only.")
    try:
        directory = resolve_desktop_directory(args.data_dir)
    except UpgradeError as exc:
        if args.smoke_test:
            raise
        message(str(exc))
        return
    directory.mkdir(parents=True, exist_ok=True)
    if args.smoke_test:
        # Isolated data folder is mandatory; never touch an existing user library.
        if not args.data_dir or (directory / "library.sqlite3").exists():
            raise SystemExit("Smoke test requires a new isolated --data-dir")
    logs = directory / "logs"
    logs.mkdir(exist_ok=True)
    from logging.handlers import RotatingFileHandler
    handler = RotatingFileHandler(logs / "desktop.log", maxBytes=1_000_000, backupCount=2, encoding="utf-8")
    logging.basicConfig(level=logging.INFO, handlers=[handler])
    lock = FileLock(str(directory / "desktop.lock"), timeout=0)
    try:
        lock.acquire()
    except Timeout:
        if not args.update_journals:
            message("SocioLibrary 已在运行，请在任务栏中打开现有窗口。")
        return
    server = None
    kernel = mutex = None
    try:
        kernel, mutex = installer_mutex()
        if args.smoke_test:
            from .smoke import seed_upgrade_fixture
            seed_upgrade_fixture(directory)
        store, config, app = initialize_desktop_library(directory)
        if args.update_journals:
            from .scheduler import discover_due
            discover_due(store, config)
            return
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app, log_config=None, access_log=False))
        thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
        thread.start()
        for _ in range(300):
            if server.started:
                break
            if not thread.is_alive():
                raise RuntimeError("本地服务启动失败，请查看本机日志。")
            time.sleep(0.1)
        else:
            raise RuntimeError("本地服务启动超时。")
        url = f"http://127.0.0.1:{port}"
        if args.smoke_test:
            assert Path(__file__).with_name("ocr.ps1").is_file(), "Windows OCR bridge missing from package"
            import webview  # noqa: F401
            from pypdf import PdfWriter
            from sentence_transformers import SentenceTransformer  # noqa: F401

            from .indexing import extract_pdf
            writer = PdfWriter()
            writer.add_blank_page(width=300, height=300)
            pdf_path = directory / "synthetic.pdf"
            with pdf_path.open("wb") as stream:
                writer.write(stream)
            assert len(extract_pdf(pdf_path)) == 1
            with httpx.Client(trust_env=False) as client:
                assert client.get(url).status_code == 200
                status = client.get(url + "/api/status").json()
                assert status["version"] == __version__
                assert client.get(url + "/static/app.js").status_code == 200
                assert client.post(url + "/api/jobs/import").status_code == 403
            from .smoke import check_upgrade_fixture
            inherited = check_upgrade_fixture(directory, store)
            (directory / "smoke-result.json").write_text(json.dumps({"ok": True, "version": __version__, **inherited}), encoding="utf-8")
            return
        remember_directory(directory)
        import webview
        bridge = DesktopAPI()
        bridge._directory = directory
        webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True
        bridge._window = webview.create_window("SocioLibrary · 社会学文献知识库", url, js_api=bridge,
                                             width=1280, height=860, min_size=(960, 680),
                                             background_color="#f4f5f0", confirm_close=True)
        def start_updates():
            from .scheduler import discover_due
            app.state.jobs.start("discover", lambda _: discover_due(store, config))
        bridge._window.events.loaded += start_updates
        webview.start(gui="edgechromium", debug=False, private_mode=True)
    except UpgradeError as exc:
        logging.exception("Upgrade initialization stopped")
        if args.smoke_test:
            raise
        message(str(exc))
    except Exception:
        logging.exception("Desktop startup failed")
        if args.smoke_test:
            raise
        message("启动未完成。研究资料仍保存在原目录，请查看资料目录 logs 中的诊断记录；窗口组件需要 Microsoft Edge WebView2 Runtime。")
    finally:
        if server:
            server.should_exit = True
        lock.release()
        if mutex:
            kernel.CloseHandle(mutex)


if __name__ == "__main__":
    main()
