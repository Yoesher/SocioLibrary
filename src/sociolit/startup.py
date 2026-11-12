"""Visible Windows initialization and per-library instance activation.

The native progress window owns a separate message loop. Database initialization
stays on the caller's thread, so desktop/library locks outlive all writes.
"""
import ctypes
import json
import logging
import os
import threading
import time

from .upgrades import UpgradeCancelled, _write


def _function(dll, name, result, *args):
    function = getattr(dll, name)
    function.restype, function.argtypes = result, list(args)
    return function


def _creation_time(pid):
    """Reject stale instance records, including Windows PID reuse."""
    from ctypes import wintypes as w
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    handle = _function(kernel, 'OpenProcess', w.HANDLE, w.DWORD, w.BOOL, w.DWORD)(0x1000, False, pid)
    if not handle:
        return None
    try:
        times = [w.FILETIME() for _ in range(4)]
        if not _function(kernel, 'GetProcessTimes', w.BOOL, w.HANDLE, *([ctypes.POINTER(w.FILETIME)] * 4))(
                handle, *(ctypes.byref(value) for value in times)):
            return None
        return (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
    finally:
        _function(kernel, 'CloseHandle', w.BOOL, w.HANDLE)(handle)


def _activate(pid):
    from ctypes import wintypes as w
    user = ctypes.WinDLL('user32', use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
    owner_pid = _function(user, 'GetWindowThreadProcessId', w.DWORD, w.HWND, ctypes.POINTER(w.DWORD))
    visible = _function(user, 'IsWindowVisible', w.BOOL, w.HWND)
    title = _function(user, 'GetWindowTextW', ctypes.c_int, w.HWND, w.LPWSTR, ctypes.c_int)
    found = []

    @callback_type
    def visit(hwnd, _):
        actual = w.DWORD()
        owner_pid(hwnd, ctypes.byref(actual))
        text = ctypes.create_unicode_buffer(256)
        if actual.value == pid and visible(hwnd):
            title(hwnd, text, len(text))
            if text.value.startswith('SocioLibrary'):
                found.append(hwnd)
        return True

    _function(user, 'EnumWindows', w.BOOL, callback_type, w.LPARAM)(visit, 0)
    if not found:
        return False
    hwnd = found[0]
    is_iconic = _function(user, 'IsIconic', w.BOOL, w.HWND)
    _function(user, 'ShowWindow', w.BOOL, w.HWND, ctypes.c_int)(hwnd, 9 if is_iconic(hwnd) else 5)
    if not _function(user, 'SetForegroundWindow', w.BOOL, w.HWND)(hwnd):
        # Respect Windows foreground restrictions; draw attention in the taskbar.
        _function(user, 'FlashWindow', w.BOOL, w.HWND, w.BOOL)(hwnd, True)
    return True


def activate_existing(directory, wait=3):
    if os.name != 'nt':
        return False
    deadline = time.monotonic() + wait
    while True:
        try:
            value = json.loads((directory / 'desktop-instance.json').read_text('utf-8'))
            pid, created = value['pid'], value['created']
            if (type(pid) is int and pid > 0 and type(created) is int
                    and _creation_time(pid) == created and _activate(pid)):
                return True
        except (OSError, ValueError, KeyError, TypeError):
            pass
        if time.monotonic() >= deadline:
            return False
        time.sleep(.1)


class DesktopInstance:
    """Only create/remove this record while holding the actual desktop FileLock."""
    def __init__(self, directory):
        self.path = directory / 'desktop-instance.json'
        self.identity = None
        if os.name == 'nt':
            created = _creation_time(os.getpid())
            if created is not None:
                self.identity = {'pid': os.getpid(), 'created': created}
                _write(self.path, self.identity)

    def close(self):
        if self.identity is not None:
            try:
                if json.loads(self.path.read_text('utf-8')) == self.identity:
                    self.path.unlink(missing_ok=True)
            except (OSError, ValueError):
                logging.warning('Could not remove the desktop instance record')


class StartupWindow:
    def __init__(self):
        self.cancelled = threading.Event()
        self._ready = threading.Event()
        self._stopped = threading.Event()
        self._state = ('正在准备资料库', None)
        self._hwnd = None
        self._thread = None

    def start(self):
        if os.name == 'nt':
            self._thread = threading.Thread(target=self._run, name='startup-window', daemon=True)
            self._thread.start()
            if not self._ready.wait(5):
                raise RuntimeError('启动进度窗口未能显示，请重新启动。')
            if self._hwnd is None:
                raise RuntimeError('无法创建启动进度窗口。')

    def update(self, stage, percent=None):
        if self.cancelled.is_set():
            raise UpgradeCancelled('已取消启动，资料仍保存在原目录。')
        state = (stage, percent)
        if state != self._state:
            if stage != self._state[0]:
                logging.info('Desktop startup: %s', stage)
            self._state = state
            self._post(0x8001)

    def _post(self, message):
        if self._hwnd:
            from ctypes import wintypes as w
            user = ctypes.WinDLL('user32', use_last_error=True)
            _function(user, 'PostMessageW', w.BOOL, w.HWND, w.UINT, w.WPARAM, w.LPARAM)(self._hwnd, message, 0, 0)

    def close(self):
        self._stopped.set()
        self._post(0x8002)
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(5)

    def _run(self):
        try:
            self._native_loop()
        except Exception:
            logging.exception('Startup progress window failed')
        finally:
            self._hwnd = None
            self._ready.set()

    def _native_loop(self):
        from ctypes import wintypes as w
        user = ctypes.WinDLL('user32', use_last_error=True)
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        proc_type = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, w.HWND, w.UINT, w.WPARAM, w.LPARAM)

        class WindowClass(ctypes.Structure):
            _fields_ = [('style', w.UINT), ('proc', proc_type), ('class_extra', ctypes.c_int),
                        ('window_extra', ctypes.c_int), ('instance', w.HINSTANCE), ('icon', w.HICON),
                        ('cursor', w.HANDLE), ('background', w.HBRUSH), ('menu', w.LPCWSTR), ('name', w.LPCWSTR)]

        default = _function(user, 'DefWindowProcW', ctypes.c_ssize_t, w.HWND, w.UINT, w.WPARAM, w.LPARAM)
        destroy = _function(user, 'DestroyWindow', w.BOOL, w.HWND)
        send = _function(user, 'SendMessageW', ctypes.c_ssize_t, w.HWND, w.UINT, w.WPARAM, w.LPARAM)
        set_text = _function(user, 'SetWindowTextW', w.BOOL, w.HWND, w.LPCWSTR)
        enable = _function(user, 'EnableWindow', w.BOOL, w.HWND, w.BOOL)
        show = _function(user, 'ShowWindow', w.BOOL, w.HWND, ctypes.c_int)
        controls = {}

        @proc_type
        def procedure(hwnd, event, wp, lp):
            if event == 0x10 or (event == 0x111 and (wp & 0xffff) == 101):
                self.cancelled.set()
                if controls:
                    set_text(controls['stage'], '正在安全停止，请稍候…')
                    enable(controls['cancel'], False)
                return 0
            if event == 0x8001 and controls and not self.cancelled.is_set():
                stage, percent = self._state
                set_text(controls['stage'], stage + (f' · {percent}%' if percent is not None else ''))
                show(controls['progress'], 5 if percent is not None else 0)
                if percent is not None:
                    send(controls['progress'], 0x402, percent, 0)
                return 0
            if event == 0x8002:
                destroy(hwnd)
                return 0
            if event == 2:
                _function(user, 'PostQuitMessage', None, ctypes.c_int)(0)
                return 0
            return default(hwnd, event, wp, lp)

        instance = _function(kernel, 'GetModuleHandleW', w.HMODULE, w.LPCWSTR)(None)
        name = f'SocioLibraryStartup{os.getpid()}'
        wc = WindowClass(0, procedure, 0, 0, instance, None, None, 6, None, name)
        atom = _function(user, 'RegisterClassW', w.WORD, ctypes.POINTER(WindowClass))(ctypes.byref(wc))
        if not atom:
            raise ctypes.WinError(ctypes.get_last_error())
        create = _function(user, 'CreateWindowExW', w.HWND, w.DWORD, w.LPCWSTR, w.LPCWSTR, w.DWORD,
                           *([ctypes.c_int] * 4), w.HWND, w.HMENU, w.HINSTANCE, ctypes.c_void_p)
        try:
            class CommonControls(ctypes.Structure):
                _fields_ = [('size', w.DWORD), ('classes', w.DWORD)]
            common = CommonControls(ctypes.sizeof(CommonControls), 0x20)
            _function(ctypes.WinDLL('comctl32'), 'InitCommonControlsEx', w.BOOL,
                      ctypes.POINTER(CommonControls))(ctypes.byref(common))
            scale = _function(user, 'GetDpiForSystem', w.UINT)() / 96
            def size(value):
                return int(value * scale)
            screen = _function(user, 'GetSystemMetrics', ctypes.c_int, ctypes.c_int)
            hwnd = create(0, name, 'SocioLibrary · 正在启动', 0x00ca0000,
                          (screen(0) - size(540)) // 2, (screen(1) - size(265)) // 2,
                          size(540), size(265), None, None, instance, None)
            if not hwnd:
                raise ctypes.WinError(ctypes.get_last_error())
            self._hwnd = hwnd
            font = _function(ctypes.WinDLL('gdi32'), 'GetStockObject', w.HANDLE, ctypes.c_int)(17)

            def control(kind, text, x, y, width, height, identifier=0, style=0):
                child = create(0, kind, text, 0x50000000 | style, size(x), size(y), size(width), size(height),
                               hwnd, identifier, instance, None)
                if not child:
                    raise ctypes.WinError(ctypes.get_last_error())
                send(child, 0x30, font, 1)
                return child

            control('STATIC', '你的资料正在本机准备', 24, 22, 485, 26)
            controls['stage'] = control('STATIC', '正在准备资料库', 24, 58, 485, 26)
            control('STATIC', '首次升级会先备份并校验原库。资料较多时需要数分钟。', 24, 92, 485, 35)
            controls['progress'] = control('msctls_progress32', '', 24, 139, 485, 16)
            controls['cancel'] = control('BUTTON', '取消启动', 397, 173, 112, 32, 101, 0x10000)
            send(controls['progress'], 0x406, 0, 100)
            show(hwnd, 5)
            self._post(0x8001)
            self._ready.set()
            if self._stopped.is_set():
                self._post(0x8002)
            msg = w.MSG()
            get_message = _function(user, 'GetMessageW', w.BOOL, ctypes.POINTER(w.MSG), w.HWND, w.UINT, w.UINT)
            translate = _function(user, 'TranslateMessage', w.BOOL, ctypes.POINTER(w.MSG))
            dispatch = _function(user, 'DispatchMessageW', ctypes.c_ssize_t, ctypes.POINTER(w.MSG))
            while get_message(ctypes.byref(msg), None, 0, 0) > 0:
                translate(ctypes.byref(msg))
                dispatch(ctypes.byref(msg))
        finally:
            if self._hwnd:
                destroy(self._hwnd)
            _function(user, 'UnregisterClassW', w.BOOL, w.LPCWSTR, w.HINSTANCE)(name, instance)
