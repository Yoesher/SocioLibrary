"""Windows and macOS desktop entry point. Installer data and research data are separate."""
import argparse
import ctypes
import json
import logging
import os
import socket
import sys
import threading
import time
import uuid
from pathlib import Path

import httpx
import uvicorn
from filelock import FileLock, Timeout

from . import __version__
from .config import read_config
from .server import create_app
from .store import Store
from .upgrades import (
    UpgradeCancelled,
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
    if os.name == 'nt':
        ctypes.windll.user32.MessageBoxW(None, text, "SocioLibrary", 0x40)
    else:
        logging.error('%s', text)


def installer_mutex():
    if os.name != 'nt':
        return None, None
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


def initialize_desktop_library(directory, progress=None):
    """Snapshot the old database before any current-version schema initialization."""
    try:
        with FileLock(str(directory / "library.lock"), timeout=1):
            report = prepare_upgrade(directory, __version__, progress=progress)
            if progress:
                progress("加载资料与设置", None)
            config = base_config()
            store = Store(directory)
            if not (directory / "preferences.json").exists():
                previous_scope = store.state("semantic_scope")
                if isinstance(previous_scope, dict) and previous_scope.get("label"):
                    config.setdefault("semantic", {})["collection_keywords"] = previous_scope["label"].split("、")
            if sys.platform == 'darwin':
                from .macos import MacUpdateManager
                app = create_app(store, config, updater=MacUpdateManager(directory, __version__), native_cocoa=True)
            else:
                app = create_app(store, config)
            complete_upgrade(directory, report)
            return store, config, app
    except Timeout as exc:
        raise UpgradeError("原资料库正在被其他任务使用，请等待同步或索引结束后重新启动。") from exc


class DesktopAPI:
    def open_source(self, file_id, page):
        from .source_links import locate
        target = locate(self._store, file_id, page)
        if not target['zotero_url']:
            return {'opened': False, 'message': '此附件不是从当前 Zotero 个人库导入，请使用本机 PDF 预览。'}
        if sys.platform == 'darwin':
            from .macos import open_zotero
            open_zotero(target['zotero_url'])
            return {'opened': True}
        if os.name != 'nt':
            return {'opened': False, 'message': '当前平台不支持原生跳转。'}
        from .zotero_launcher import launch
        launch(target['zotero_url'])
        return {'opened': True}

    def update_context(self):
        from .update_install import native_install_context
        context = native_install_context()
        return {key: context[key] for key in ("supported", "mode", "message")}

    def install_update(self):
        from .software_updates import UpdateError
        from .update_install import launch_install_helper, native_install_context
        context = native_install_context()
        if not context["supported"]:
            raise UpdateError(context["message"])
        if not self._native_lock.acquire(blocking=False):
            raise UpdateError("请先完成笔记导出，再执行升级。")
        if self._app.state.jobs.snapshot()["state"] == "running":
            self._native_lock.release()
            raise UpdateError("请先等待同步、索引或 OCR 任务完成，再升级。")
        if not self._app.state.operation_lock.acquire(blocking=False):
            self._native_lock.release()
            raise UpdateError("当前资料操作尚未完成，请稍后升级。")
        self._app.state.maintenance.set()
        handoff = None
        try:
            with FileLock(str(self._directory / "library.lock"), timeout=0):
                release, installer = self._app.state.updater.ready_installer()
                handoff = launch_install_helper(installer, release, self._directory, context["target"])
                self._helper = handoff
                self._app.state.updater.register_handoff(release.version, handoff["result_file"])
            self._window.confirm_close = False
            self._window.destroy()
            return {"installing": True}
        except Timeout as exc:
            self._app.state.maintenance.clear()
            raise UpdateError("资料库正在被其他任务使用，请等待任务完成后升级。") from exc
        except Exception:
            self._app.state.maintenance.clear()
            self._window.confirm_close = True
            if handoff:
                from .upgrades import _write
                try:
                    _write(handoff["result_file"], {"version": release.version, "success": False, "cancelled": True,
                        "error": "Application did not close for installation"})
                except OSError:
                    logging.exception("Could not persist update cancellation")
                try:
                    if handoff["process"].poll() is None:
                        handoff["process"].terminate()
                except OSError:
                    logging.exception("Could not stop waiting update helper")
            raise
        finally:
            self._app.state.operation_lock.release()
            self._native_lock.release()

    def export_notes(self):
        with self._native_lock:
            return self._export_notes()

    def _export_notes(self):
        import webview

        from .research import notes_markdown
        paths = self._window.create_file_dialog(webview.SAVE_DIALOG, directory=str(self._directory), save_filename="SocioLibrary-阅读笔记.md",
                                                file_types=("Markdown (*.md)",))
        if not paths:
            return {"saved": False}
        path = Path(paths[0])
        if path.suffix.lower() != ".md":
            path = path.with_name(path.name + ".md")
        temp = path.with_name("." + path.name + "." + uuid.uuid4().hex + ".tmp")
        try:
            with temp.open("w", encoding="utf-8") as output:
                for block in notes_markdown(self._store):
                    output.write(block)
            os.replace(temp, path)
        finally:
            temp.unlink(missing_ok=True)
        return {"saved": True}

    def choose_folder(self):
        import webview
        result = self._window.create_file_dialog(webview.FOLDER_DIALOG)
        return result[0] if result else None

    def export_comparison(self, identity, format, revision):
        import re

        import webview

        from . import comparisons
        if not isinstance(identity, str) or not re.fullmatch(r"[a-f0-9]{32}", identity) or format not in ("md", "csv"):
            raise ValueError("导出参数无效。")
        with self._native_lock:
            content = comparisons.export(self._store, identity, format, revision)
            paths = self._window.create_file_dialog(webview.SAVE_DIALOG, directory=str(self._directory),
                save_filename="SocioLibrary-文献对照." + format,
                file_types=(("CSV (*.csv)" if format == "csv" else "Markdown (*.md)"),))
            if not paths:
                return {"saved": False}
            path = Path(paths[0])
            if path.suffix.lower() != "." + format:
                path = path.with_name(path.name + "." + format)
            temp = path.with_name("." + path.name + "." + uuid.uuid4().hex + ".tmp")
            try:
                with temp.open("w", encoding="utf-8-sig" if format == "csv" else "utf-8", newline="") as output:
                    output.write(content)
                os.replace(temp, path)
            finally:
                temp.unlink(missing_ok=True)
            return {"saved": True}

    def export_graph(self, identity, include_annotations=False):
        import re

        import webview

        from . import graph_views
        if not isinstance(identity, str) or not re.fullmatch(r'[a-f0-9]{32}', identity) or type(include_annotations) is not bool:
            raise ValueError('导出参数无效。')
        with self._native_lock, FileLock(str(self._directory / 'library.lock'), timeout=1):
            content = graph_views.export(self._store, identity, include_annotations)
            paths = self._window.create_file_dialog(webview.SAVE_DIALOG, directory=str(self._directory),
                save_filename='SocioLibrary-research.zip', file_types=('ZIP (*.zip)',))
            if not paths:
                return {'saved': False}
            path = Path(paths[0])
            if path.suffix.lower() != '.zip':
                path = path.with_name(path.name + '.zip')
            if path.resolve().is_relative_to(self._directory.resolve()):
                raise ValueError('研究包请保存到资料库以外的导出文件夹。')
            temp = path.with_name('.' + path.name + '.' + uuid.uuid4().hex + '.tmp')
            try:
                temp.write_bytes(content)
                os.replace(temp, path)
            finally:
                temp.unlink(missing_ok=True)
            return {'saved': True}

    def open_data_folder(self):
        if sys.platform == 'darwin':
            __import__('subprocess').Popen(['/usr/bin/open', str(self._directory)])
        else:
            os.startfile(str(self._directory))
        return True

    def open_releases(self):
        import webbrowser
        webbrowser.open("https://github.com/Yoesher/SocioLibrary/releases")

    def open_update_folder(self):
        directory = self._app.state.updater.cache_directory()
        directory.mkdir(parents=True, exist_ok=True)
        if sys.platform == 'darwin':
            __import__('subprocess').Popen(['/usr/bin/open', str(directory)])
        else:
            os.startfile(str(directory))
        return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument("--gui-smoke-test", action="store_true")
    parser.add_argument("--data-dir")
    parser.add_argument("--update-journals", action="store_true")
    args = parser.parse_args()
    if args.gui_smoke_test and (os.environ.get('GITHUB_ACTIONS') != 'true' or not args.data_dir):
        raise SystemExit('GUI smoke mode is limited to isolated build runners')
    if sys.platform not in ("win32", "darwin"):
        raise SystemExit("Desktop distribution supports Windows and macOS.")
    try:
        directory = resolve_desktop_directory(args.data_dir)
    except UpgradeError as exc:
        if args.smoke_test or args.gui_smoke_test:
            raise
        message(str(exc))
        return
    directory.mkdir(parents=True, exist_ok=True)
    if args.smoke_test or args.gui_smoke_test:
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
            from .startup import activate_existing
            if not activate_existing(directory):
                message("SocioLibrary 正在启动或运行。请稍候查看启动进度窗口；若仍未显示，请查看资料目录 logs 中的启动记录。")
        return
    server = None
    update_stop = threading.Event()
    kernel = mutex = None
    startup = instance = None
    try:
        kernel, mutex = installer_mutex()
        from .startup import DesktopInstance, StartupWindow
        instance = DesktopInstance(directory)
        if not (args.smoke_test or args.update_journals):
            startup = StartupWindow()
            startup.start()
        if args.smoke_test or args.gui_smoke_test:
            from .smoke import seed_upgrade_fixture
            seed_upgrade_fixture(directory)
        store, config, app = initialize_desktop_library(directory, progress=startup.update if startup else None)
        if args.update_journals:
            from .scheduler import discover_due
            discover_due(store, config)
            return
        if startup:
            startup.update("打开研究工作台", None)
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
            assert Path(__file__).with_name("update.ps1").is_file(), "Windows updater helper missing from package"
            import webview  # noqa: F401
            from pypdf import PdfWriter
            if not (sys.platform == 'darwin' and __import__('platform').machine() == 'x86_64'):
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
                assert client.get(url + "/static/ai.js").status_code == 200
                assert client.get(url + "/static/literature.js").status_code == 200
                for asset in ('graph-notebooks.js', 'journal-inbox.js', 'journals.js', 'network.js', 'papers.js', 'navigation.js', 'desktop-ui.css', 'cytoscape-3.35.0.min.js', 'cytoscape-LICENSE.txt'):
                    assert client.get(url + '/static/' + asset).status_code == 200
                paper_results = client.post(url + '/api/search/papers', json={'query': 'synthetic', 'mode': 'fulltext'},
                    headers={'X-Sociolit-Token': status['token']}).json()
                assert paper_results['total'] >= 1 and paper_results['papers'][0]['abstract'] is not None
                assert client.get(url + "/static/appearance.css").status_code == 200
                assert client.get(url + "/static/workbench.js").status_code == 200
                assert client.get(url + '/static/design-studio.js').status_code == 200
                assert client.get(url + '/static/design-system.css').status_code == 200
                assert client.get(url + '/static/graph-core.js').status_code == 200
                assert client.get(url + '/static/graph-studio.css').status_code == 200
                configured_journals = client.get(url + '/api/journals', headers={'X-Sociolit-Token': status['token']}).json()
                assert any(j['name'] == 'Synthetic Custom Journal' and not j['enabled'] for j in configured_journals)
                expansion = client.post(url + '/api/graph/expand',
                    headers={'X-Sociolit-Token': status['token']},
                    json={'seed': 'synthetic:item', 'known_ids': ['synthetic:item'], 'include_auto': False})
                assert expansion.status_code == 200 and expansion.json()['added_ids'] == ['synthetic:gone']
                assert any(n['id'] == 'synthetic:gone' and not n['current'] for n in expansion.json()['nodes'])
                assert client.get(url + '/api/appearance', headers={'X-Sociolit-Token': status['token']}).json()['design'] == 'apple'
                assert len(client.get(url + "/api/comparisons", headers={"X-Sociolit-Token": status["token"]}).json()) == 1
                assert client.get(url + "/api/annotations?include_missing=true",
                    headers={"X-Sociolit-Token": status["token"]}).json()["total"] == 1
                assert client.get(url + "/api/appearance", headers={"X-Sociolit-Token": status["token"]}).json()["theme"] == "ink"
                assert len(client.post(url + "/api/graph", json={"seed": "synthetic:item", "include_auto": False},
                    headers={"X-Sociolit-Token": status["token"]}).json()["edges"]) == 1
                ai_response = client.get(url + "/api/ai/profiles", headers={"X-Sociolit-Token": status["token"]})
                assert ai_response.status_code == 200
                if os.name == "nt":
                    assert ai_response.json()["profiles"][0]["has_key"]
                assert "synthetic-smoke-secret" not in ai_response.text
                assert client.post(url + "/api/jobs/import").status_code == 403
            from .smoke import check_upgrade_fixture
            from .update_install import native_install_context
            inherited = check_upgrade_fixture(directory, store)
            context = native_install_context()
            assert context["supported"] == (sys.platform == "win32" and bool(getattr(sys, "frozen", False)))
            (directory / "smoke-result.json").write_text(json.dumps({"ok": True, "version": __version__,
                "updater_mode": context["mode"], **inherited}), encoding="utf-8")
            return
        if not args.gui_smoke_test:
            remember_directory(directory)
        import webview
        bridge = DesktopAPI()
        bridge._directory = directory
        bridge._app = app
        bridge._store = store
        bridge._native_lock = threading.Lock()
        webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True
        bridge._window = webview.create_window("SocioLibrary · 社会学文献知识库", url, js_api=bridge,
                                             width=1280, height=860, min_size=(960, 680),
                                             background_color="#f4f5f0", confirm_close=True)
        if startup:
            def finish_startup():
                startup.close()
                if startup.cancelled.is_set():
                    bridge._window.confirm_close = False
                    bridge._window.destroy()
            bridge._window.events.loaded += finish_startup
        def start_updates():
            if startup and startup.cancelled.is_set():
                return
            from .scheduler import discover_due
            try:
                app.state.jobs.start("discover", lambda _: discover_due(store, config))
            except RuntimeError:
                pass
            try:
                app.state.updater.check(automatic=True)
            except RuntimeError:
                pass
        if args.gui_smoke_test:
            def gui_check():
                from .update_install import native_install_context
                value = {'ok': False}
                try:
                    if os.name == 'nt':
                        import subprocess
                        value['startup_window'] = bool(startup and startup._ready.is_set())
                        duplicate = subprocess.run([sys.executable, '--data-dir', str(directory)], timeout=30,
                                                   check=False)
                        value['repeat_launch'] = duplicate.returncode == 0
                    # Closing inside a native callback can strand WebKit's pending
                    # return-value worker. Wait until its promise has resolved.
                    bridge._window.run_js("window.pywebview.api.update_context().then(function(c){window.__sociolitSmokeContext=c.mode;}).catch(function(){window.__sociolitSmokeContext='error';});")
                    for _ in range(200):
                        value.update(bridge._window.evaluate_js("({version:document.getElementById('version').textContent, notebooks:!!document.getElementById('graph-view-save'), inbox:!!document.getElementById('journal-inbox-form'), native_bridge:window.__sociolitSmokeContext||''})"))
                        if isinstance(value, dict) and value.get('native_bridge') and value.get('version'):
                            break
                        time.sleep(.05)
                    value['ok'] = (__version__ in str(value.get('version'))
                                   and value.get('notebooks') is True and value.get('inbox') is True
                                   and value.get('native_bridge') == native_install_context()['mode']
                                   and (os.name != 'nt' or (value.get('startup_window') and value.get('repeat_launch'))))
                except Exception as exc:
                    logging.exception('Native GUI check failed')
                    value = {'ok': False, 'error_type': type(exc).__name__}
                finally:
                    (directory / 'gui-smoke-result.json').write_text(json.dumps(value), encoding='utf-8')
                    bridge._window.confirm_close = False
                    bridge._window.destroy()
            bridge._window.events.loaded += gui_check
        else:
            bridge._window.events.loaded += start_updates
        def periodic_updates():
            while not update_stop.wait(3600):
                try:
                    app.state.updater.check(automatic=True)
                except RuntimeError:
                    pass
        threading.Thread(target=periodic_updates, daemon=True).start()
        webview.start(gui="cocoa" if sys.platform == "darwin" else "edgechromium", debug=False, private_mode=True)
    except UpgradeCancelled:
        logging.info("Desktop startup cancelled safely")
    except UpgradeError as exc:
        logging.exception("Upgrade initialization stopped")
        if args.smoke_test or args.gui_smoke_test:
            raise
        message(str(exc))
    except Exception:
        logging.exception("Desktop startup failed")
        if args.smoke_test or args.gui_smoke_test:
            raise
        message("启动未完成。研究资料仍保存在原目录，请查看资料目录 logs 中的诊断记录；Windows 窗口组件需要 Microsoft Edge WebView2 Runtime；Mac 请查看应用启动日志。")
    finally:
        update_stop.set()
        if startup:
            startup.close()
        if server:
            server.should_exit = True
        if instance:
            instance.close()
        lock.release()
        if mutex:
            kernel.CloseHandle(mutex)


if __name__ == "__main__":
    main()
