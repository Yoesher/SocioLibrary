"""Hand a verified installer to a separate process before closing the desktop app."""
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

from .software_updates import UpdateError, verify_installer


def native_install_context():
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return {"supported": False, "mode": "source", "message": "源码运行可检查和下载更新；一键安装需使用 Windows 桌面发布版。"}
    import winreg

    current = Path(sys.executable).resolve().parent
    registered = None
    key = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\{9DA31A80-0D44-4490-87B0-8F3B9FA7D6AB}_is1"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as handle:
            value = winreg.QueryValueEx(handle, "InstallLocation")[0]
            if value and Path(value).is_absolute():
                registered = Path(value).resolve()
    except OSError:
        pass
    installed = registered == current
    target = current if installed else registered or Path(os.environ["LOCALAPPDATA"]) / "Programs/SocioLibrary"
    return {"supported": True, "mode": "installed" if installed else "portable",
            "target": str(target), "message": "" if installed else "免安装版将升级为安装版，原资料目录保持不变。"}


def launch_install_helper(installer, release, data_directory, target_directory, *, cache=None, test_mode=False):
    if sys.platform != "win32":
        raise UpdateError("一键安装目前只支持 Windows。")
    if test_mode and os.environ.get("GITHUB_ACTIONS") != "true":
        raise UpdateError("安装验证模式只允许在临时构建环境运行。")
    verify_installer(installer, release)
    data = Path(data_directory).resolve()
    target = Path(target_directory).resolve()
    if (not data.is_absolute() or target == Path(target.anchor) or data.is_relative_to(target)
            or any(character in str(target) + str(data) for character in ('"', '\r', '\n'))):
        raise UpdateError("程序目录与资料目录冲突，已停止自动安装。")
    folder = Path(cache).resolve() if cache else Path(installer).resolve().parent
    folder.mkdir(parents=True, exist_ok=True)
    nonce = uuid.uuid4().hex
    ready = folder / ("handoff-" + nonce + ".ready.json")
    result = folder / ("handoff-" + nonce + ".result.json")
    request = {"request_id": nonce, "parent_pid": os.getpid(), "installer": str(Path(installer).resolve()),
               "sha256": release.digest, "size": release.size, "version": release.version,
               "data_dir": str(data), "target_dir": str(target), "fallback_exe": str(Path(sys.executable).resolve()),
               "ready_file": str(ready), "result_file": str(result), "test_mode": test_mode}
    script = Path(__file__).with_name("update.ps1").read_text(encoding="utf-8")
    powershell = Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    environment = {key: value for key, value in os.environ.items() if key.casefold() != "psmodulepath"}
    # A PowerShell 7 parent can otherwise shadow the Windows PowerShell 5.1 system modules.
    environment["PSModulePath"] = str(powershell.parent / "Modules")
    with (folder / ("handoff-" + nonce + ".helper.log")).open("wb") as diagnostic:
        process = subprocess.Popen([str(powershell), "-NoProfile", "-NonInteractive", "-Command", script],
                                   stdin=subprocess.PIPE, stdout=diagnostic, stderr=subprocess.STDOUT,
                                   text=True, encoding="utf-8", creationflags=subprocess.CREATE_NO_WINDOW, env=environment)
    try:
        process.stdin.write(json.dumps(request, ensure_ascii=False))
        process.stdin.close()
        for _ in range(600):
            if ready.is_file():
                response = json.loads(ready.read_text(encoding="utf-8-sig"))
                if response.get("request_id") != nonce:
                    raise UpdateError("安装交接记录异常，软件继续保留当前版本。")
                return {"process": process, "result_file": result}
            if process.poll() is not None:
                break
            time.sleep(0.05)
    except (OSError, ValueError) as exc:
        if process.poll() is None:
            process.terminate()
        raise UpdateError("无法启动更新安装助手，当前软件未关闭。") from exc
    if process.poll() is None:
        process.terminate()
    raise UpdateError("安装助手未能就绪，当前软件未关闭，请稍后重试。")
