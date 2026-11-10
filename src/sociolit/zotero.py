"""Read-only, loopback-only Zotero adapter; never opens a Zotero database.

Local API versions before Zotero 10 do not reliably reflect local changes. A
complete metadata snapshot is therefore returned on each call; the application
deduplicates records and hashes attachment content before rebuilding its index.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable
from urllib.parse import unquote, urlsplit
from urllib.request import url2pathname

import httpx


class ZoteroError(RuntimeError):
    """An import could not produce a reliable snapshot."""


@dataclass
class Attachment:
    key: str
    parent_key: str
    path: Path | None
    warning: str | None = None


@dataclass
class Snapshot:
    source_id: str
    items: list[dict]
    attachments: list[Attachment]
    complete: bool
    warnings: list[str] = field(default_factory=list)


def _roots(values: Iterable[str | Path]) -> list[Path]:
    roots = []
    for value in values:
        raw = str(value)
        if raw.startswith(("\\\\", "//")):
            raise ZoteroError("附件许可目录必须是本地目录，不能是网络共享。")
        roots.append(Path(value).expanduser().resolve())
    return roots


def local_pdf_path(value: str, allowed_roots: Iterable[str | Path]) -> Path:
    """Resolve only an existing local PDF inside an explicitly allowed root.

    Resolving before containment also blocks symlink escapes. Never fetches the
    URL and never permits UNC paths, even if a UNC root was supplied.
    """
    if not value or "\x00" in value:
        raise ZoteroError("附件没有有效的本地路径。")
    if value.lower().startswith("file:"):
        parsed = urlsplit(value)
        if parsed.scheme != "file" or parsed.netloc not in ("", "localhost"):
            raise ZoteroError("拒绝网络共享附件路径。")
        if parsed.query or parsed.fragment:
            raise ZoteroError("附件 file URL 不得包含查询参数或片段。")
        raw = url2pathname(parsed.path)
    else:
        raw = value
        # Windows drive prefixes are paths, but other schemes are not.
        if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", raw) and not re.match(r"^[A-Za-z]:[\\/]", raw):
            raise ZoteroError("附件必须是本地文件，不能是网络地址。")
    if raw.startswith(("\\\\", "//")):
        raise ZoteroError("拒绝网络共享附件路径。")
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise ZoteroError("附件路径必须是绝对路径。")
    path = path.resolve()
    if str(path).startswith(("\\\\", "//")):
        raise ZoteroError("拒绝网络共享附件路径。")
    if path.suffix.lower() != ".pdf":
        raise ZoteroError("此附件不是 PDF。")
    roots = _roots(allowed_roots)
    if not any(path.is_relative_to(root) for root in roots):
        raise ZoteroError("PDF 不在已授权的附件目录中；请在本地配置中添加目录。")
    if not path.is_file():
        raise ZoteroError("PDF 尚未下载到本机，或原文件已移动。")
    return path


def _authors(data: dict) -> list[str]:
    values = data.get("creators", data.get("author", [])) or []
    names = []
    for value in values:
        if isinstance(value, str):
            names.append(value)
        elif isinstance(value, dict):
            name = value.get("name") or value.get("literal") or " ".join(
                str(value.get(k) or "") for k in ("firstName", "lastName")
            ).strip() or " ".join(str(value.get(k) or "") for k in ("given", "family")).strip()
            if name:
                names.append(name)
    return names


def _normalized(data: dict, key: str) -> dict:
    date = str(data.get("date") or "")
    year_match = re.search(r"\b(1[0-9]{3}|20[0-9]{2})\b", date)
    year = int(year_match.group()) if year_match else None
    if year is None:
        parts = (data.get("issued") or {}).get("date-parts", [])
        if parts and parts[0]:
            try:
                year = int(parts[0][0])
            except (TypeError, ValueError):
                pass
    tags = []
    for tag in data.get("tags", []) or []:
        text = tag.get("tag") if isinstance(tag, dict) else str(tag)
        if text:
            tags.append(text)
    doi = str(data.get("DOI") or data.get("doi") or "").strip()
    doi = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", doi, flags=re.I).lower()
    return {
        "key": key,
        "title": str(data.get("title") or ("Zotero 笔记" if data.get("itemType") == "note" else "未命名文献")),
        "authors": _authors(data),
        "year": year,
        "doi": doi,
        "abstract": str(data.get("abstractNote") or data.get("abstract") or ""),
        "tags": tags,
        "item_type": str(data.get("itemType") or data.get("type") or "document"),
        "journal": str(data.get("publicationTitle") or data.get("container-title") or ""),
        "url": str(data.get("url") or data.get("URL") or ""),
        "raw": data,
    }


class ZoteroClient:
    """A read-only client for the current user's local Zotero library.

    ``allowed_roots`` must name the storage/linked-file directories the user has
    chosen. An empty list imports metadata while reporting PDF access warnings.
    ``legacy_namespace`` identifies databases without a Zotero-Server-ID header;
    change it when switching Zotero profiles on older Zotero versions.
    """

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:23119/api",
        allowed_roots: Iterable[str | Path] = (),
        timeout: float = 30.0,
        legacy_namespace: str = "default",
        transport: httpx.BaseTransport | None = None,
        progress=None,
    ):
        parsed = urlsplit(base_url)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in ("127.0.0.1", "localhost", "::1")
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path.rstrip("/") != "/api"
        ):
            raise ZoteroError("Zotero 地址必须是本机 http://127.0.0.1:23119/api。")
        try:
            port = parsed.port or 23119
        except ValueError as exc:
            raise ZoteroError("Zotero 端口无效。") from exc
        # Resolve localhost ourselves: do not allow DNS/proxy settings to turn a
        # supposedly local request into an off-machine request.
        host = "[::1]" if parsed.hostname == "::1" else "127.0.0.1"
        self.base_url = f"http://{host}:{port}/api"
        self.allowed_roots = _roots(allowed_roots)
        self.legacy_namespace = legacy_namespace
        self.progress = progress or (lambda phase, done, total: None)
        self._client = httpx.Client(
            timeout=timeout,
            follow_redirects=False,
            trust_env=False,
            transport=transport,
            headers={"Zotero-API-Version": "3", "Accept": "application/json"},
        )

    def __enter__(self) -> "ZoteroClient":
        return self

    def __exit__(self, *_args) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def source_id(self, server_id: str | None) -> str:
        identity = server_id or "legacy:" + hashlib.sha256(
            f"{self.base_url}|{self.legacy_namespace}".encode()
        ).hexdigest()[:20]
        return "zotero:" + identity

    def collections(self) -> tuple[str, list[dict]]:
        response = self._get("/users/0/collections?format=json")
        if response.status_code != 200 or re.search(r'rel=["\']?next', response.headers.get("Link", ""), re.I):
            raise ZoteroError("Zotero 分类目录未能完整读取。")
        try:
            records = response.json()
            total = response.headers.get("Total-Results")
            if not isinstance(records, list) or (total and int(total) != len(records)):
                raise ValueError("incomplete collection list")
            output = []
            seen = set()
            for record in records:
                data = record["data"]
                key = str(record.get("key") or data.get("key") or "")
                name = data.get("name")
                if not re.fullmatch(r"[A-Z0-9]{8}", key) or key in seen or not isinstance(name, str):
                    raise ValueError("invalid collection")
                seen.add(key)
                output.append({"key": key, "name": name, "parent": data.get("parentCollection") or ""})
            return self.source_id(response.headers.get("Zotero-Server-ID")), output
        except (ValueError, TypeError, KeyError) as exc:
            raise ZoteroError("Zotero 分类目录格式不正确，未执行试点索引。") from exc

    def _get(self, path: str, server_id: str | None = None) -> httpx.Response:
        headers = {"Zotero-Server-ID": server_id} if server_id else {}
        try:
            response = self._client.get(self.base_url + path, headers=headers)
        except httpx.HTTPError as exc:
            raise ZoteroError("无法连接本机 Zotero；请打开 Zotero 并启用本地 API。") from exc
        if response.status_code == 403:
            raise ZoteroError("请在 Zotero 设置 → 高级中开启“允许此计算机上的其他应用与 Zotero 通信”。")
        if response.status_code == 412:
            raise ZoteroError("导入期间 Zotero 数据库已切换；请重新导入。")
        if response.is_redirect:
            raise ZoteroError("Zotero API 返回重定向，已拒绝跟随。")
        if server_id and response.headers.get("Zotero-Server-ID", server_id) != server_id:
            raise ZoteroError("导入期间 Zotero 实例已切换；请重新导入。")
        return response

    def snapshot(self) -> Snapshot:
        # Limit pages only when Zotero provides a local instance ID and a
        # library version. Otherwise use a single unpaginated legacy snapshot:
        # older Zotero versions cannot prove stability between pages.
        response = self._get("/users/0/items?format=json&include=data&limit=100&start=0")
        if response.status_code != 200:
            raise ZoteroError(f"Zotero 文献读取失败（HTTP {response.status_code}）。")
        try:
            records = response.json()
        except ValueError as exc:
            raise ZoteroError("Zotero 返回了无效 JSON，未执行导入。") from exc
        if not isinstance(records, list):
            raise ZoteroError("Zotero 返回格式不正确，未执行导入。")
        total = response.headers.get("Total-Results")
        next_page = bool(re.search(r'rel=["\']?next', response.headers.get("Link", ""), re.I))
        server_id = response.headers.get("Zotero-Server-ID")
        library_version = response.headers.get("Last-Modified-Version")
        if next_page and server_id and library_version and total:
            try:
                expected = int(total)
            except ValueError as exc:
                raise ZoteroError("Zotero 返回无效文献总数，未执行导入。") from exc
            if expected < len(records) or expected > 1_000_000:
                raise ZoteroError("Zotero 文献总数异常，未执行导入。")
            while len(records) < expected:
                start = len(records)
                page = self._get(f"/users/0/items?format=json&include=data&limit=100&start={start}", server_id)
                if (page.status_code != 200 or page.headers.get("Last-Modified-Version") != library_version
                        or page.headers.get("Total-Results") != total):
                    raise ZoteroError("导入时 Zotero 文献库发生变化；请稍后重试。")
                try:
                    values = page.json()
                except ValueError as exc:
                    raise ZoteroError("Zotero 分页返回无效 JSON，未执行导入。") from exc
                if not isinstance(values, list) or not values or len(values) > 100 or start + len(values) > expected:
                    raise ZoteroError("Zotero 分页不完整或数量异常，未执行导入。")
                records.extend(values)
                self.progress("metadata", len(records), expected)
        elif next_page:
            # Never follow Zotero-provided links or assume old versions are stable.
            response = self._get("/users/0/items?format=json&include=data")
            if response.status_code != 200 or re.search(r'rel=["\']?next', response.headers.get("Link", ""), re.I):
                raise ZoteroError("Zotero 未返回完整文献列表；请重试。")
            try:
                records = response.json()
            except ValueError as exc:
                raise ZoteroError("Zotero 返回无效 JSON，未执行导入。") from exc
            if not isinstance(records, list):
                raise ZoteroError("Zotero 返回格式不正确，未执行导入。")
            total = response.headers.get("Total-Results")
            server_id = response.headers.get("Zotero-Server-ID")
            library_version = None
        if total:
            try:
                if int(total) != len(records):
                    raise ZoteroError("Zotero 未返回完整文献列表；请重试。")
            except ValueError as exc:
                raise ZoteroError("Zotero 返回无效文献总数，未执行导入。") from exc
        snapshot = Snapshot(self.source_id(server_id), [], [], True)
        if not server_id:
            snapshot.warnings.append("本机 Zotero 未返回实例标识；切换旧版 Zotero 数据库时请更换 legacy_namespace。")
        seen: set[str] = set()
        attachment_data = []
        for record in records:
            if not isinstance(record, dict) or not isinstance(record.get("data"), dict):
                raise ZoteroError("Zotero 条目格式不完整，未执行导入。")
            data = record["data"]
            key = str(record.get("key") or data.get("key") or "")
            if not re.fullmatch(r"[A-Z0-9]{8}", key) or key in seen:
                raise ZoteroError("Zotero 条目标识无效或重复，未执行导入。")
            seen.add(key)
            if data.get("deleted") or data.get("inTrash"):
                continue
            kind = data.get("itemType")
            if kind == "attachment":
                if data.get("contentType") == "application/pdf" or str(data.get("filename", "")).lower().endswith(".pdf"):
                    attachment_data.append((key, data))
                    if not data.get("parentItem"):
                        snapshot.items.append(_normalized(data, key))
            elif kind != "annotation":
                snapshot.items.append(_normalized(data, key))
        item_keys = {item["key"] for item in snapshot.items}
        for position, (key, data) in enumerate(attachment_data, 1):
            parent = str(data.get("parentItem") or key)
            if parent not in item_keys:
                snapshot.warnings.append(f"附件 {key} 的父条目不可用，已跳过。")
                continue
            file_response = self._get(f"/users/0/items/{key}/file/view/url", server_id)
            warning = None
            path = None
            if file_response.status_code != 200:
                warning = f"PDF 路径不可用（HTTP {file_response.status_code}），请确认附件已下载到本机。"
            else:
                try:
                    path = local_pdf_path(file_response.text.strip(), self.allowed_roots)
                except ZoteroError as exc:
                    warning = str(exc)
            snapshot.attachments.append(Attachment(key, parent, path, warning))
            if warning:
                snapshot.warnings.append(f"附件 {key}：{warning}")
            self.progress("attachment_paths", position, len(attachment_data))
        if next_page and server_id and library_version:
            final = self._get("/users/0/items?format=versions&limit=1", server_id)
            if (final.status_code != 200 or final.headers.get("Last-Modified-Version") != library_version
                    or final.headers.get("Total-Results") != total):
                raise ZoteroError("导入时 Zotero 文献库发生变化；请稍后重试。")
        return snapshot


def load_export(path: str | Path, allowed_roots: Iterable[str | Path] = ()) -> Snapshot:
    """Read a user-selected Zotero/Better BibTeX/CSL JSON export offline.

    CSL JSON contains metadata only. Native/Better BibTeX JSON can also contain
    attachment ``path``/``localPath`` values, which are subject to the same root
    allowlist. Relative export paths are interpreted relative to the export.
    Export imports are independent snapshots and never prune a live API source.
    """
    export_path = Path(path).expanduser().resolve()
    try:
        content = json.loads(export_path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise ZoteroError("无法读取所选 JSON 导出文件。") from exc
    records = content.get("items") if isinstance(content, dict) else content
    if not isinstance(records, list):
        raise ZoteroError("导出文件应为 JSON 条目数组或包含 items 数组的对象。")
    snapshot = Snapshot("export:" + hashlib.sha256(str(export_path).encode()).hexdigest()[:20], [], [], True)
    roots = _roots(allowed_roots)
    seen = set()
    for record in records:
        if not isinstance(record, dict):
            raise ZoteroError("导出文件中包含无效条目。")
        data = record.get("data", record)
        if not isinstance(data, dict):
            raise ZoteroError("导出文件中包含无效条目数据。")
        identifier = data.get("key") or data.get("itemKey") or data.get("id") or data.get("citationKey")
        key = str(identifier) if identifier else "item:" + hashlib.sha256(
            json.dumps(data, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()[:20]
        if key in seen:
            raise ZoteroError("导出文件包含重复条目标识。")
        seen.add(key)
        if data.get("deleted") or data.get("inTrash"):
            continue
        snapshot.items.append(_normalized(data, key))
        for number, attachment in enumerate(data.get("attachments", []) or []):
            if not isinstance(attachment, dict):
                continue
            attachment_key = str(attachment.get("key") or attachment.get("itemKey") or f"{key}:pdf:{number}")
            value = attachment.get("path") or attachment.get("localPath")
            if not value:
                continue
            value = str(value)
            if not value.lower().startswith("file:") and not Path(value).is_absolute() and not re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", value):
                value = str(export_path.parent / value)
            if not unquote(value).lower().endswith(".pdf"):
                continue
            pdf_path = None
            warning = None
            try:
                pdf_path = local_pdf_path(value, roots)
            except ZoteroError as exc:
                warning = str(exc)
                snapshot.warnings.append(f"附件 {attachment_key}：{warning}")
            snapshot.attachments.append(Attachment(attachment_key, key, pdf_path, warning))
    return snapshot
