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
from .config import default_data_dir, read_config
from .server import create_app
from .store import Store


def base_config():
    bundled = Path(__file__).parent / "defaults" / "public-journals.toml"
    source = Path(__file__).resolve().parents[2] / "config" / "public-journals.toml"
    return read_config(bundled if bundled.is_file() else source)


def message(text):
    ctypes.windll.user32.MessageBoxW(None, text, "SocioLibrary", 0x40)


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
    directory = Path(args.data_dir).resolve() if args.data_dir else default_data_dir()
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
    config = base_config()
    store = Store(directory)
    # Preserve a previously selected semantic pilot when upgrading from the source version.
    # PDF roots still require an explicit selection in the new desktop settings.
    if not (directory / "preferences.json").exists():
        previous_scope = store.state("semantic_scope")
        if isinstance(previous_scope, dict) and previous_scope.get("label"):
            config.setdefault("semantic", {})["collection_keywords"] = previous_scope["label"].split("、")
    from .subscriptions import apply_feeds
    apply_feeds(store, config)
    if args.update_journals:
        from .scheduler import discover_due
        discover_due(store, config)
        return
    lock = FileLock(str(directory / "desktop.lock"), timeout=0)
    try:
        lock.acquire()
    except Timeout:
        message("SocioLibrary 已在运行，请在任务栏中打开现有窗口。")
        return
    server = None
    try:
        app = create_app(store, config)
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
            (directory / "smoke-result.json").write_text(json.dumps({"ok": True, "version": __version__}), encoding="utf-8")
            return
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
    except Exception:
        logging.exception("Desktop startup failed")
        if args.smoke_test:
            raise
        message("启动遇到问题。请确认已安装 Microsoft Edge WebView2 Runtime。诊断记录保存在资料目录 logs 中。")
    finally:
        if server:
            server.should_exit = True
        lock.release()


if __name__ == "__main__":
    main()
