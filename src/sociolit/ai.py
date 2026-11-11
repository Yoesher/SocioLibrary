"""Explicit, user-configured AI connections. No background calls or document uploads."""
import base64
import ctypes
import ipaddress
import json
import os
import re
import sys
import time
import uuid
from hashlib import sha256
from urllib.parse import urlsplit

import httpx
from filelock import FileLock, Timeout

from .upgrades import _write

PRESETS = [
    {"id": "openai", "name": "OpenAI（ChatGPT API）", "protocol": "responses",
     "base_url": "https://api.openai.com/v1", "model": ""},
    {"id": "compatible", "name": "自定义 OpenAI 兼容服务", "protocol": "chat",
     "base_url": "", "model": ""},
    {"id": "anthropic", "name": "Anthropic / Claude", "protocol": "anthropic",
     "base_url": "https://api.anthropic.com/v1", "model": ""},
    {"id": "gemini", "name": "Google Gemini（兼容接口）", "protocol": "chat",
     "base_url": "https://generativelanguage.googleapis.com/v1beta/openai", "model": ""},
    {"id": "deepseek", "name": "DeepSeek", "protocol": "chat",
     "base_url": "https://api.deepseek.com", "model": ""},
    {"id": "qwen", "name": "通义千问 / 百炼（填写控制台地址）", "protocol": "chat",
     "base_url": "", "model": ""},
    {"id": "ollama", "name": "Ollama 本机服务", "protocol": "chat",
     "base_url": "http://127.0.0.1:11434/v1", "model": ""},
    {"id": "lmstudio", "name": "LM Studio 本机服务", "protocol": "chat",
     "base_url": "http://127.0.0.1:1234/v1", "model": ""},
]
PROTOCOLS = {"responses", "chat", "anthropic"}


class AIError(RuntimeError):
    """Messages are safe to show: never include provider bodies, headers or credentials."""


def normalize_url(value):
    if not isinstance(value, str) or len(value) > 1000 or re.search(r"[\s\\\x00-\x1f\x7f]", value):
        raise AIError("API 地址无效，请填写服务商提供的基础地址。")
    try:
        parsed = urlsplit(value)
        port = parsed.port
        host = parsed.hostname
    except ValueError as exc:
        raise AIError("API 地址无效。") from exc
    if (not host or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.scheme not in ("http", "https") or port == 0):
        raise AIError("地址不能包含账号、密码、查询参数或片段；云端必须使用 HTTPS。")
    local = host.lower() == "localhost"
    try:
        address = ipaddress.ip_address(host)
        local = address.is_loopback
        if not local and not address.is_global:
            raise AIError("仅支持公网 HTTPS 或本机回环服务地址。")
    except ValueError:
        pass
    if parsed.scheme == "http" and not local:
        raise AIError("HTTP 仅允许本机 localhost、127.0.0.1 或 ::1；云端请使用 HTTPS。")
    path = parsed.path.rstrip("/")
    if ("%" in parsed.netloc or any(segment in (".", "..") for segment in path.split("/"))
            or path.endswith(("/responses", "/chat/completions", "/messages"))):
        raise AIError("请填写基础地址，不要包含 responses、chat/completions 或 messages 接口后缀。")
    return f"{parsed.scheme}://{parsed.netloc.lower()}{path}"


def is_local(url):
    host = urlsplit(url).hostname
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


class WindowsProtector:
    """DPAPI user scope; no plaintext fallback and no third-party vault dependency."""
    def _transform(self, data, context, decrypt=False):
        if os.name != "nt":
            raise AIError("当前版本仅支持在 Windows 当前账号下加密保存 API 密钥。")
        from ctypes import wintypes

        class Blob(ctypes.Structure):
            _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]

        def blob(value):
            buffer = ctypes.create_string_buffer(value)
            return Blob(len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))), buffer

        source, _source_buffer = blob(data)
        entropy, _entropy_buffer = blob(context.encode("utf-8"))
        output = Blob()
        crypt = ctypes.WinDLL("crypt32", use_last_error=True)
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.LocalFree.argtypes = [ctypes.c_void_p]
        kernel.LocalFree.restype = ctypes.c_void_p
        method = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
        method.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p if decrypt else wintypes.LPCWSTR,
                           ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                           wintypes.DWORD, ctypes.POINTER(Blob)]
        method.restype = wintypes.BOOL
        # CRYPTPROTECT_UI_FORBIDDEN; deliberately no LOCAL_MACHINE scope.
        if not method(ctypes.byref(source), None if decrypt else "SocioLibrary API key",
                      ctypes.byref(entropy), None, None, 1, ctypes.byref(output)):
            raise AIError("密钥加密或解密失败。请在原 Windows 账号下使用，或重新填写密钥。")
        try:
            return ctypes.string_at(output.pbData, output.cbData)
        finally:
            kernel.LocalFree(output.pbData)

    def protect(self, text, context):
        return base64.b64encode(self._transform(text.encode(), context)).decode("ascii")

    def unprotect(self, text, context):
        try:
            return self._transform(base64.b64decode(text, validate=True), context, True).decode("utf-8")
        except (ValueError, UnicodeError) as exc:
            raise AIError("密钥记录无效，请重新填写；不会尝试明文读取。") from exc


class MacKeychainProtector:
    """Only the macOS Keychain backend; never a plaintext or automatic fallback."""
    service = 'org.yoesher.sociolibrary'

    def __init__(self, backend=None):
        self.backend = backend

    def _backend(self):
        if self.backend is None:
            try:
                from keyring.backends.macOS import Keyring
                self.backend = Keyring()
            except Exception:
                raise AIError('无法访问 macOS 钥匙串，请检查系统授权；不会明文保存密钥。') from None
        return self.backend

    def protect(self, text, context):
        identity = uuid.uuid4().hex
        try:
            self._backend().set_password(self.service, identity, json.dumps({'context': sha256(context.encode()).hexdigest(), 'secret': text}))
        except Exception:
            raise AIError('无法写入 macOS 钥匙串，密钥未保存，请检查系统授权。') from None
        return 'keychain:' + identity

    def unprotect(self, text, context):
        if not re.fullmatch(r'keychain:[a-f0-9]{32}', text):
            raise AIError('这份密钥不属于当前 Mac 钥匙串，请重新填写密钥。')
        try:
            value = json.loads(self._backend().get_password(self.service, text[9:]) or '{}')
            if value.get('context') != sha256(context.encode()).hexdigest() or not isinstance(value.get('secret'), str):
                raise ValueError
            return value['secret']
        except Exception:
            raise AIError('无法从 macOS 钥匙串读取该连接的密钥，请重新填写。') from None


def _context(profile):
    return "SocioLibrary:" + ":".join(profile[key] for key in ("id", "protocol", "base_url"))


def profile_revision(profile):
    return sha256(json.dumps(profile, sort_keys=True).encode()).hexdigest()


class Profiles:
    def __init__(self, directory, protector=None):
        self.path = directory / "ai-profiles.json"
        self.protector = protector or (MacKeychainProtector() if sys.platform == 'darwin' else WindowsProtector())
        self.lock = FileLock(str(directory / "ai-profiles.lock"), timeout=1)

    def _read(self):
        if not self.path.exists():
            return {"version": 1, "profiles": []}
        try:
            if self.path.stat().st_size > 256000:
                raise ValueError("oversized")
            value = json.loads(self.path.read_text(encoding="utf-8"))
            if (value.get("version") != 1 or not isinstance(value.get("profiles"), list)
                    or len(value["profiles"]) > 20):
                raise ValueError("schema")
            ids = set()
            for profile in value["profiles"]:
                if (not isinstance(profile, dict) or not re.fullmatch(r"[a-f0-9]{32}", profile["id"])
                        or profile["id"] in ids or profile["protocol"] not in PROTOCOLS
                        or normalize_url(profile["base_url"]) != profile["base_url"]
                        or not isinstance(profile["name"], str) or len(profile["name"]) > 80
                        or not isinstance(profile["model"], str) or len(profile["model"]) > 150
                        or type(profile["max_output_tokens"]) is not int
                        or not 256 <= profile["max_output_tokens"] <= 8192
                        or profile.get("token_parameter", "auto") not in ("auto", "max_tokens", "max_completion_tokens")
                        or type(profile.get("disable_thinking", False)) is not bool
                        or not isinstance(profile.get("encrypted_key", ""), str)):
                    raise ValueError("profile")
                ids.add(profile["id"])
            return value
        except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
            raise AIError("AI 配置无法读取，原文件已保留；文献检索仍可使用。请检查本机 AI 配置备份。") from exc

    def list(self):
        profiles = []
        for profile in self._read()["profiles"]:
            public = {key: profile.get(key) for key in ("id", "name", "protocol", "base_url", "model",
                       "max_output_tokens", "token_parameter", "disable_thinking")}
            public["has_key"] = bool(profile.get("encrypted_key"))
            public["local"] = is_local(profile["base_url"])
            profiles.append(public)
        return {"profiles": profiles, "presets": PRESETS}

    def get(self, identity):
        for profile in self._read()["profiles"]:
            if profile["id"] == identity:
                return profile
        raise AIError("AI 连接不存在，请重新选择或配置。")

    def save(self, *, identity, name, protocol, base_url, model, max_output_tokens, api_key=None,
             clear_key=False, token_parameter="auto", disable_thinking=False):
        name, model = name.strip(), model.strip()
        if (not 1 <= len(name) <= 80 or not 1 <= len(model) <= 150 or protocol not in PROTOCOLS
                or re.search(r"[\x00-\x1f\x7f]", name + model)
                or not isinstance(max_output_tokens, int) or not 256 <= max_output_tokens <= 8192):
            raise AIError("请填写连接名称、正确的协议和模型 ID，输出上限为 256–8192 tokens。")
        base_url = normalize_url(base_url.strip())
        if token_parameter not in ("auto", "max_tokens", "max_completion_tokens") or type(disable_thinking) is not bool:
            raise AIError("兼容选项无效，请重新选择。")
        if api_key is not None:
            api_key = api_key.strip()
            if (not 1 <= len(api_key) <= 4096 or not api_key.isascii()
                    or re.search(r"[\s\x00-\x1f\x7f]", api_key)):
                raise AIError("API 密钥无效，请检查是否混入空格或换行。")
        try:
            with self.lock:
                value = self._read()
                old = next((row for row in value["profiles"] if row["id"] == identity), None)
                if identity and not old:
                    raise AIError("连接已不存在，请重新读取列表。")
                if not old and len(value["profiles"]) >= 20:
                    raise AIError("最多保留 20 个 AI 连接，请先移除不用的连接。")
                profile = {"id": identity or uuid.uuid4().hex, "name": name, "protocol": protocol,
                           "base_url": base_url, "model": model, "max_output_tokens": max_output_tokens,
                           "token_parameter": token_parameter, "disable_thinking": disable_thinking}
                if api_key:
                    profile["encrypted_key"] = self.protector.protect(api_key, _context(profile))
                elif old and not clear_key and _context(old) == _context(profile):
                    profile["encrypted_key"] = old.get("encrypted_key", "")
                else:
                    profile["encrypted_key"] = ""
                value["profiles"] = [row for row in value["profiles"] if row["id"] != profile["id"]] + [profile]
                _write(self.path, value)
        except Timeout as exc:
            raise AIError("AI 设置正在保存，请稍后重试。") from exc
        return {"id": profile["id"], "saved": True, "has_key": bool(profile["encrypted_key"])}

    def delete(self, identity):
        try:
            with self.lock:
                value = self._read()
                value["profiles"] = [row for row in value["profiles"] if row["id"] != identity]
                _write(self.path, value)
        except Timeout as exc:
            raise AIError("AI 设置正在保存，请稍后重试。") from exc
        return {"deleted": True}

    def key(self, profile):
        encrypted = profile.get("encrypted_key")
        if encrypted:
            return self.protector.unprotect(encrypted, _context(profile))
        if not is_local(profile["base_url"]):
            raise AIError("该云端连接尚未保存密钥；修改地址或协议后需要重新填写密钥。")
        return ""


def request_payload(profile, system, prompt, *, test=False):
    limit = 64 if test else profile["max_output_tokens"]
    protocol = profile["protocol"]
    if protocol == "responses":
        return "/responses", {"model": profile["model"], "instructions": system, "input": prompt,
                              "max_output_tokens": limit, "store": False, "stream": False}
    messages = [{"role": "user", "content": prompt}]
    if protocol == "anthropic":
        return "/messages", {"model": profile["model"], "system": system, "messages": messages,
                             "max_tokens": limit, "stream": False}
    messages.insert(0, {"role": "system", "content": system})
    body = {"model": profile["model"], "messages": messages, "stream": False}
    official = urlsplit(profile["base_url"]).hostname == "api.openai.com"
    token_parameter = profile.get("token_parameter", "auto")
    if token_parameter == "auto":
        token_parameter = "max_completion_tokens" if official else "max_tokens"
    body[token_parameter] = limit
    if profile.get("disable_thinking"):
        body["enable_thinking"] = False
    if official:
        body["store"] = False
    return "/chat/completions", body


def _usage(value):
    if not isinstance(value, dict):
        return {}
    result = {}
    for target, keys in (("input_tokens", ("input_tokens", "prompt_tokens")),
                         ("output_tokens", ("output_tokens", "completion_tokens"))):
        for key in keys:
            if type(value.get(key)) is int and 0 <= value[key] < 10**10:
                result[target] = value[key]
                break
    return result


def parse_answer(value, protocol):
    try:
        warning = ""
        if protocol == "responses":
            status = value.get("status")
            if status not in ("completed", "incomplete"):
                raise AIError("服务商未返回已完成的文本答复，请检查模型和协议。")
            texts = [part["text"] for item in value["output"] if item.get("type") == "message"
                     for part in item.get("content", []) if part.get("type") == "output_text"]
            warning = "达到输出限制，答复可能不完整。" if status == "incomplete" else ""
        elif protocol == "anthropic":
            texts = [part["text"] for part in value["content"] if part.get("type") == "text"]
            warning = "达到输出限制，答复可能不完整。" if value.get("stop_reason") == "max_tokens" else ""
        else:
            choice = value["choices"][0]
            content = choice["message"].get("content")
            if isinstance(content, list):
                texts = [part["text"] for part in content if part.get("type") == "text"]
            else:
                texts = [content]
            warning = "达到输出限制，答复可能不完整。" if choice.get("finish_reason") == "length" else ""
        if not texts or any(not isinstance(text, str) for text in texts) or not "".join(texts).strip():
            raise ValueError("no text")
        text = "\n".join(texts)
        if len(text) > 100000:
            raise ValueError("oversized answer")
        return {"text": text, "usage": _usage(value.get("usage")), "warning": warning}
    except (KeyError, IndexError, TypeError, ValueError, AttributeError) as exc:
        raise AIError("服务商返回的内容不是该协议的文本答复；请检查协议和模型 ID。") from exc


def call_ai(profile, key, system, prompt, *, test=False, factory=None):
    """One billable attempt only. No automatic retries, redirects, tools or file uploads."""
    suffix, body = request_payload(profile, system, prompt, test=test)
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if key:
        if profile["protocol"] == "anthropic":
            headers["x-api-key"] = key
        else:
            headers["Authorization"] = "Bearer " + key
    if profile["protocol"] == "anthropic":
        headers["anthropic-version"] = "2023-06-01"
    factory = factory or (lambda: httpx.Client(timeout=httpx.Timeout(120, connect=15),
                                               follow_redirects=False, trust_env=False))
    try:
        started = time.monotonic()
        with factory() as client, client.stream("POST", profile["base_url"] + suffix,
                                                json=body, headers=headers, follow_redirects=False) as response:
            status = response.status_code
            if status != 200:
                message = {401: "密钥未通过认证", 403: "账号或模型访问未获许可", 404: "地址、模型或协议未找到",
                           429: "额度不足或请求过于频繁"}.get(status, "服务商暂时无法完成请求")
                raise AIError(f"{message}（HTTP {status}）。未自动重试；超时或失败也可能产生服务商费用。")
            data = bytearray()
            for part in response.iter_bytes():
                if time.monotonic() - started > 120:
                    raise AIError("接收答复时间超过上限，已停止；未自动重试，服务商可能已计费。")
                data.extend(part)
                if len(data) > 2 * 1024 * 1024:
                    raise AIError("服务商答复超过大小上限，已停止接收。")
            value = json.loads(data)
        # A reasoning-only, output-limited test still proves authentication and model access.
        if (test and profile["protocol"] == "responses" and isinstance(value, dict)
                and value.get("status") == "incomplete" and isinstance(value.get("output"), list)
                and isinstance(value.get("incomplete_details"), dict)
                and value["incomplete_details"].get("reason") == "max_output_tokens"):
            result = {"text": "", "usage": _usage(value.get("usage")),
                      "warning": "固定测试已获接受，但推理或输出达到测试上限；完整生成尚未验证。"}
        else:
            result = parse_answer(value, profile["protocol"])
        # Never expose a key if a malfunctioning provider echoes request headers.
        if key:
            result["text"] = result["text"].replace(key, "[密钥已隐藏]")
        return result
    except (httpx.HTTPError, OSError) as exc:
        raise AIError("连接失败或等待超时；请核对网络与 API 设置。未自动重试，服务商可能已计费。") from exc
    except (ValueError, UnicodeError) as exc:
        raise AIError("服务商返回了无法读取的 JSON 答复。") from exc
