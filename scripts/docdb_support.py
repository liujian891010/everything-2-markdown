#!/usr/bin/env python3
"""Shared helpers for document naming and cms-docdb ingestion."""
from __future__ import annotations

import json
import os
import re
import ssl
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path


SEARCH_API_URL = "https://sg-al-cwork-web.mediportal.com.cn/open-api/document-database/file/searchFile"
UPLOAD_API_URL = "https://sg-al-cwork-web.mediportal.com.cn/open-api/document-database/file/uploadContent"
SCRIPT_DIR = Path(__file__).resolve().parent
AUTH_SCRIPT = (
    SCRIPT_DIR.parent.parent / "cms-auth-skills" / "scripts" / "auth" / "login.py"
)
SSL_CONTEXT = ssl.create_default_context()
SSL_CONTEXT.check_hostname = False
SSL_CONTEXT.verify_mode = ssl.CERT_NONE


def normalize_space(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def sanitize_file_stem(title: str, fallback: str = "文档") -> str:
    normalized = normalize_space(title)
    if not normalized:
        normalized = fallback
    normalized = re.sub(r"[<>:\"/\\\\|?*\r\n\t]+", "-", normalized)
    normalized = re.sub(r"\s+", "-", normalized)
    normalized = re.sub(r"-{2,}", "-", normalized).strip("-")
    if not normalized:
        normalized = fallback
    return normalized[:80]


def folder_name_for_source(source_type: str, input_kind: str | None = None) -> str:
    if source_type in {"youtube_url", "douyin_url"}:
        return "视频链接"
    if source_type in {"generic_url", "toutiao_url"}:
        return "网页链接"
    if source_type == "uploaded_file":
        return "本地文件"
    if source_type == "plain_text":
        if input_kind == "chat_log":
            return "钉钉聊天"
        return "文本输入"
    return "文本输入"


def resolve_app_key(
    explicit_app_key: str | None = None,
    *,
    sender_id: str | None = None,
    account_id: str | None = None,
    context_json: str = "",
    required: bool = False,
) -> str | None:
    app_key = explicit_app_key or os.getenv("XG_BIZ_API_KEY") or os.getenv("XG_APP_KEY")
    if app_key:
        return app_key

    has_auth_context = bool(sender_id or account_id or context_json)
    if required and not has_auth_context:
        raise RuntimeError("缺少 appKey。请传入 --app-key，或提供可解析 appKey 的鉴权上下文。")
    if not required and not has_auth_context:
        return None

    if not AUTH_SCRIPT.exists():
        if required:
            raise RuntimeError("未找到 cms-auth-skills/login.py，无法自动解析 appKey。")
        return None

    command = [sys.executable, str(AUTH_SCRIPT), "--resolve-app-key"]
    if sender_id:
        command.extend(["--sender-id", sender_id])
    if account_id:
        command.extend(["--account-id", account_id])
    if context_json:
        command.extend(["--context-json", context_json])

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        if required:
            detail = (result.stderr or result.stdout or "").strip()
            raise RuntimeError(f"自动获取 appKey 失败: {detail}")
        return None

    lines = (result.stdout or "").strip().splitlines()
    resolved = lines[-1].strip() if lines else ""
    if resolved:
        return resolved

    if required:
        raise RuntimeError("自动获取 appKey 失败: 返回为空")
    return None


def _request_json(url: str, *, method: str, headers: dict, body: dict | None = None) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, context=SSL_CONTEXT, timeout=60) as response:
            raw = response.read()
            charset = response.headers.get_content_charset() or "utf-8"
            return json.loads(raw.decode(charset))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {raw}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"URL error: {exc.reason}") from exc


def _iter_strings(payload):
    if isinstance(payload, str):
        yield payload
        return
    if isinstance(payload, dict):
        for value in payload.values():
            yield from _iter_strings(value)
        return
    if isinstance(payload, list):
        for item in payload:
            yield from _iter_strings(item)


def next_sequence_for_today(app_key: str | None, date_prefix: str) -> int:
    if not app_key:
        return 1

    query = urllib.parse.urlencode({"nameKey": date_prefix})
    headers = {"appKey": app_key, "Content-Type": "application/json"}
    try:
        result = _request_json(
            f"{SEARCH_API_URL}?{query}",
            method="GET",
            headers=headers,
        )
    except Exception:
        return 1

    pattern = re.compile(rf"^{re.escape(date_prefix)}(\d{{3}})-")
    max_sequence = 0
    for value in _iter_strings(result.get("data") if isinstance(result, dict) else result):
        match = pattern.match(normalize_space(value))
        if match:
            max_sequence = max(max_sequence, int(match.group(1)))
    return max_sequence + 1 if max_sequence else 1


def build_file_name(
    title: str,
    *,
    source_type: str,
    input_kind: str | None = None,
    app_key: str | None = None,
    suffix: str = "md",
) -> dict:
    today = date.today().isoformat()
    next_sequence = next_sequence_for_today(app_key, f"{today}-")
    stem = sanitize_file_stem(title, fallback=folder_name_for_source(source_type, input_kind))
    file_name = f"{today}-{next_sequence:03d}-{stem}.{suffix}"
    return {
        "fileName": file_name,
        "fileSuffix": suffix,
        "folderName": folder_name_for_source(source_type, input_kind),
        "sequence": next_sequence,
        "datePrefix": today,
    }


def upload_markdown_document(
    *,
    markdown: str,
    file_name: str,
    folder_name: str,
    app_key: str,
    file_suffix: str = "md",
) -> dict:
    payload = {
        "content": markdown,
        "fileName": file_name,
        "fileSuffix": file_suffix,
        "folderName": folder_name,
    }
    result = _request_json(
        UPLOAD_API_URL,
        method="POST",
        headers={"appKey": app_key, "Content-Type": "application/json"},
        body=payload,
    )
    if isinstance(result, dict) and result.get("resultCode") not in (None, 1):
        raise RuntimeError(result.get("resultMsg") or "cms-docdb 入库失败")
    return result


def build_document_result(
    *,
    markdown: str,
    title: str,
    source_type: str,
    input_kind: str | None = None,
    ingest: bool = False,
    explicit_app_key: str | None = None,
    sender_id: str | None = None,
    account_id: str | None = None,
    context_json: str = "",
) -> dict:
    preview_app_key = resolve_app_key(
        explicit_app_key,
        sender_id=sender_id,
        account_id=account_id,
        context_json=context_json,
        required=True,
    )
    document_meta = build_file_name(
        title,
        source_type=source_type,
        input_kind=input_kind,
        app_key=preview_app_key,
    )

    result = {
        "markdown": markdown,
        "document": document_meta,
    }

    upload_result = upload_markdown_document(
        markdown=markdown,
        file_name=document_meta["fileName"],
        folder_name=document_meta["folderName"],
        file_suffix=document_meta["fileSuffix"],
        app_key=preview_app_key,
    )
    result.update(
        {
            "phase": "ingested",
            "ingestResult": upload_result.get("data", upload_result),
        }
    )
    return result
