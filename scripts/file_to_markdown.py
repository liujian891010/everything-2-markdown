#!/usr/bin/env python3
"""Uploaded file flow for everything-2-markdown."""
from __future__ import annotations

import argparse
import csv
import html
import json
import mimetypes
import os
import re
import ssl
import subprocess
import sys
import urllib.error
import urllib.request
import uuid
import zipfile
from datetime import date
from pathlib import Path
from xml.etree import ElementTree as ET

from docdb_support import build_document_result
from document_renderer import (
    build_content_blocks_from_sections,
    build_content_blocks_from_text,
    polish_key_points,
    polish_summary,
    render_document,
)


TEXT_EXTENSIONS = {
    ".txt",
    ".md",
    ".markdown",
    ".html",
    ".htm",
    ".json",
    ".csv",
    ".tsv",
    ".log",
    ".xml",
    ".yaml",
    ".yml",
}

LOCAL_LIGHT_OFFICE_EXTENSIONS = {
    ".docx",
    ".pptx",
    ".xlsx",
}

API_DIRECT_EXTENSIONS = {
    ".pdf",
    ".doc",
    ".ppt",
    ".xls",
}

IMAGE_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".gif",
    ".bmp",
    ".tiff",
}

DEFAULT_TOKEN_HEADER = "access-token"
DEFAULT_TIMEOUT_SECONDS = 300
DEFAULT_API_BASE_URL = "https://sg-al-cwork-web.mediportal.com.cn"
DEFAULT_API_PATH = "/open-api/file-processing-service/v1/convert/upload-sync"
LOCAL_OFFICE_MIN_LENGTH = 40
MAX_TABLE_ROWS = 20
MAX_TABLE_COLS = 8
SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
AUTH_SCRIPT = SKILL_DIR.parent / "cms-auth-skills" / "scripts" / "auth" / "login.py"
SSL_CONTEXT = ssl.create_default_context()
SSL_CONTEXT.check_hostname = False
SSL_CONTEXT.verify_mode = ssl.CERT_NONE
NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "ss": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert an uploaded local file into a markdown document."
    )
    parser.add_argument("file_path", help="Local file path")
    parser.add_argument(
        "--api-url",
        default=os.getenv("FILE_PROCESSING_API_URL", ""),
        help="Full upload-sync API URL",
    )
    parser.add_argument(
        "--api-base-url",
        default=(
            os.getenv("FILE_PROCESSING_BASE_URL")
            or os.getenv("XG_FILE_PROCESSING_BASE_URL")
            or os.getenv("FILE_PROCESSING_DOMAIN")
            or DEFAULT_API_BASE_URL
        ),
        help="Service domain or base URL used to build the upload-sync API URL",
    )
    parser.add_argument("--token", help="Explicit access token")
    parser.add_argument("--app-key", help="Optional appKey used to resolve token")
    parser.add_argument("--sender-id", help="Optional sender_id used to resolve token")
    parser.add_argument("--account-id", help="Optional account_id used to resolve token")
    parser.add_argument("--context-json", default="", help="Optional auth context JSON")
    parser.add_argument(
        "--header-name",
        default=os.getenv("FILE_PROCESSING_TOKEN_HEADER", DEFAULT_TOKEN_HEADER),
        help="HTTP header name used for token authentication",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="Request timeout in seconds",
    )
    parser.add_argument(
        "--mock-response-file",
        help="Use a local JSON file instead of calling the remote API",
    )
    parser.add_argument(
        "--ingest",
        action="store_true",
        help="Upload the generated markdown document to cms-docdb",
    )
    return parser.parse_args()


def normalize_space(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def detect_file_kind(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in TEXT_EXTENSIONS:
        return "text_file"
    if suffix in LOCAL_LIGHT_OFFICE_EXTENSIONS or suffix in API_DIRECT_EXTENSIONS:
        return "office_file"
    if suffix in IMAGE_EXTENSIONS:
        return "image_file"
    return "unknown_file"


def guess_mime(path: Path) -> str:
    mime, _ = mimetypes.guess_type(str(path))
    return mime or "application/octet-stream"


def resolve_api_url(args: argparse.Namespace) -> str:
    if args.api_url:
        return args.api_url.strip()
    if not args.api_base_url:
        raise RuntimeError("缺少文件解析服务域名，请传入 --api-url 或 --api-base-url。")

    base_url = args.api_base_url.strip()
    if not re.match(r"^https?://", base_url, re.IGNORECASE):
        base_url = f"https://{base_url}"
    return f"{base_url.rstrip('/')}{DEFAULT_API_PATH}"


def resolve_token(args: argparse.Namespace) -> str:
    explicit = (
        args.token
        or os.getenv("XG_USER_TOKEN")
        or os.getenv("ACCESS_TOKEN")
        or os.getenv("FILE_PROCESSING_ACCESS_TOKEN")
    )
    if explicit:
        return explicit

    if not AUTH_SCRIPT.exists():
        raise RuntimeError(
            "未找到 cms-auth-skills 的 login.py，无法自动解析 token。请显式传入 --token。"
        )

    command = [sys.executable, str(AUTH_SCRIPT), "--ensure"]
    if args.app_key:
        command.extend(["--app-key", args.app_key])
    if args.sender_id:
        command.extend(["--sender-id", args.sender_id])
    if args.account_id:
        command.extend(["--account-id", args.account_id])
    if args.context_json:
        command.extend(["--context-json", args.context_json])

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"自动获取 token 失败: {detail}")

    lines = (result.stdout or "").strip().splitlines()
    token_value = lines[-1].strip() if lines else ""
    if not token_value:
        raise RuntimeError("自动获取 token 失败: 返回为空")
    return token_value


def load_mock_payload(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def build_multipart_form(file_path: Path) -> tuple[bytes, str]:
    boundary = f"----easyclaw-{uuid.uuid4().hex}"
    file_name = file_path.name.replace('"', '\\"')
    mime = guess_mime(file_path)
    file_bytes = file_path.read_bytes()

    parts = [
        f"--{boundary}\r\n".encode("utf-8"),
        f'Content-Disposition: form-data; name="file"; filename="{file_name}"\r\n'.encode("utf-8"),
        f"Content-Type: {mime}\r\n\r\n".encode("utf-8"),
        file_bytes,
        b"\r\n",
        f"--{boundary}--\r\n".encode("utf-8"),
    ]
    return b"".join(parts), boundary


def upload_file_sync(
    *,
    api_url: str,
    file_path: Path,
    token: str,
    header_name: str,
    timeout_seconds: int,
) -> dict:
    body, boundary = build_multipart_form(file_path)
    request = urllib.request.Request(
        api_url,
        data=body,
        headers={
            header_name: token,
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(
            request,
            timeout=max(timeout_seconds, 1),
            context=SSL_CONTEXT,
        ) as response:
            raw = response.read()
            charset = response.headers.get_content_charset() or "utf-8"
            text = raw.decode(charset, errors="replace")
            try:
                return json.loads(text)
            except ValueError as exc:
                raise RuntimeError("文件解析接口返回了非 JSON 响应") from exc
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"文件解析请求失败: HTTP {exc.code} {raw}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"文件解析请求失败: {exc.reason}") from exc


def pick_first_string(payload, keys: tuple[str, ...]) -> str | None:
    if isinstance(payload, dict):
        for key in keys:
            value = payload.get(key)
            if isinstance(value, str) and normalize_space(value):
                return value.strip()
        for value in payload.values():
            found = pick_first_string(value, keys)
            if found:
                return found
    elif isinstance(payload, list):
        for item in payload:
            found = pick_first_string(item, keys)
            if found:
                return found
    return None


def pick_first_list(payload, keys: tuple[str, ...]) -> list | None:
    if isinstance(payload, dict):
        for key in keys:
            value = payload.get(key)
            if isinstance(value, list) and value:
                return value
        for value in payload.values():
            found = pick_first_list(value, keys)
            if found:
                return found
    elif isinstance(payload, list):
        for item in payload:
            found = pick_first_list(item, keys)
            if found:
                return found
    return None


def pick_first_scalar(payload, keys: tuple[str, ...]) -> str | None:
    if isinstance(payload, dict):
        for key in keys:
            value = payload.get(key)
            if value not in (None, "", [], {}):
                return normalize_space(str(value))
        for value in payload.values():
            found = pick_first_scalar(value, keys)
            if found:
                return found
    elif isinstance(payload, list):
        for item in payload:
            found = pick_first_scalar(item, keys)
            if found:
                return found
    return None


def extract_result_payload(payload):
    if not isinstance(payload, dict):
        return payload
    for key in ("data", "result", "payload"):
        value = payload.get(key)
        if value not in (None, "", [], {}):
            return value
    return payload


def extract_service_message(payload: dict) -> str:
    return (
        pick_first_string(
            payload,
            (
                "resultMsg",
                "detailMsg",
                "message",
                "msg",
                "error",
                "errorMsg",
                "errorMessage",
            ),
        )
        or "文件解析失败"
    )


def is_success_payload(payload: dict) -> bool:
    if not isinstance(payload, dict):
        return False

    success_value = pick_first_string(payload, ("status", "state"))
    if success_value and success_value.lower() in {"success", "succeeded", "done", "completed"}:
        return True

    for key in ("ok", "success"):
        value = payload.get(key)
        if isinstance(value, bool):
            return value

    result_code = payload.get("resultCode")
    if result_code in (None, "", 0, 1, 200, "0", "1", "200"):
        extracted = extract_result_payload(payload)
        return extracted not in (None, "", [], {})
    return False


def sanitize_title(file_path: Path, payload) -> str:
    title = pick_first_string(
        payload,
        (
            "title",
            "name",
            "documentName",
            "fileName",
            "filename",
            "originFileName",
            "sourceFileName",
        ),
    )
    if title:
        return normalize_space(title)
    return file_path.stem or file_path.name


def strip_markdown(text: str) -> str:
    cleaned = re.sub(r"```[\s\S]*?```", " ", text)
    cleaned = re.sub(r"`([^`]+)`", r"\1", cleaned)
    cleaned = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", cleaned)
    cleaned = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", cleaned)
    cleaned = re.sub(r"^\s{0,3}#+\s*", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"^\s*[-*+]\s+", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"^\s*\d+\.\s+", "", cleaned, flags=re.MULTILINE)
    return normalize_space(cleaned)


def split_sentences(text: str) -> list[str]:
    normalized = normalize_space(text)
    if not normalized:
        return []
    parts = re.split(r"(?<=[。！？!?；;])\s*", normalized)
    return [part.strip() for part in parts if part.strip()]


def normalize_key_points(value) -> list[str]:
    if not value:
        return []

    items = value if isinstance(value, list) else [value]
    normalized: list[str] = []
    for item in items:
        if isinstance(item, str):
            text = normalize_space(item)
        elif isinstance(item, dict):
            text = (
                pick_first_string(
                    item,
                    ("text", "point", "content", "summary", "title", "name"),
                )
                or ""
            )
        else:
            text = normalize_space(str(item))

        if text:
            normalized.append(text)
        if len(normalized) >= 5:
            break
    return normalized


def build_key_points(text: str) -> list[str]:
    sentences = split_sentences(strip_markdown(text))
    if sentences:
        return sentences[:3]
    compact = strip_markdown(text)
    if not compact:
        return []
    chunks = [chunk.strip() for chunk in re.split(r"[，,]", compact) if chunk.strip()]
    return chunks[:3] if chunks else [compact[:120]]


def build_summary(summary: str | None, key_points: list[str], content: str) -> str:
    if summary and normalize_space(summary):
        return normalize_space(summary)

    cleaned_points = [point.rstrip("。；;!！?？") for point in key_points if point.strip()]
    if cleaned_points:
        if len(cleaned_points) == 1:
            return f"这个文件主要在讲：{cleaned_points[0]}。"
        if len(cleaned_points) == 2:
            return f"这个文件主要包含两个重点：{cleaned_points[0]}；{cleaned_points[1]}。"
        return (
            "这个文件主要围绕以下内容展开："
            f"{cleaned_points[0]}；{cleaned_points[1]}；{cleaned_points[2]}。"
        )

    compact = strip_markdown(content)
    if not compact:
        return "文件已处理，但没有提取到可用正文。"
    return compact[:180] + ("..." if len(compact) > 180 else "")


def looks_like_markdown(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    markers = ("# ", "## ", "- ", "* ", "```", "> ", "| ")
    return any(marker in stripped for marker in markers)


def build_sections_markdown(sections) -> str:
    if not isinstance(sections, list) or not sections:
        return ""

    rendered: list[str] = []
    for index, item in enumerate(sections, start=1):
        if isinstance(item, str):
            text = normalize_space(item)
            if text:
                rendered.append(f"### 第 {index} 部分\n\n{text}")
            continue

        if not isinstance(item, dict):
            text = normalize_space(str(item))
            if text:
                rendered.append(f"### 第 {index} 部分\n\n{text}")
            continue

        title = (
            pick_first_string(item, ("title", "name", "heading", "header", "sectionTitle"))
            or f"第 {index} 部分"
        )
        body = (
            pick_first_string(
                item,
                ("markdown", "content", "text", "body", "pageText", "pageContent"),
            )
            or ""
        )
        if not body:
            body = json.dumps(item, ensure_ascii=False, indent=2)
            body = f"```json\n{body}\n```"
        rendered.append(f"### {title}\n\n{body.strip()}")
    return "\n\n".join(rendered)


def organize_body(content: str, sections_markdown: str) -> str:
    content = (content or "").strip()
    if looks_like_markdown(content):
        return content
    if content:
        lines = [line.strip() for line in content.splitlines()]
        paragraphs: list[str] = []
        bucket: list[str] = []
        for line in lines:
            if not line:
                if bucket:
                    paragraphs.append(" ".join(bucket))
                    bucket = []
                continue
            bucket.append(line)
        if bucket:
            paragraphs.append(" ".join(bucket))
        if paragraphs:
            return "\n\n".join(paragraphs)
        return normalize_space(content)
    if sections_markdown:
        return sections_markdown
    return "暂无可用正文。"


def bullets_from_key_points(key_points: list[str]) -> str:
    if not key_points:
        return "- 暂无明确关键点"
    return "\n".join(f"- {point}" for point in key_points)


def build_metadata_lines(file_path: Path, file_kind: str, mime: str, payload) -> str:
    lines = [
        "> 来源：本地文件",
        f"> 文件：{file_path.name}",
        f"> 文件类型：{file_kind}",
        f"> MIME：{mime}",
        f"> 整理日期：{date.today().isoformat()}",
    ]

    page_count = pick_first_scalar(payload, ("pageCount", "page_count", "totalPages"))
    parser_name = pick_first_scalar(payload, ("parser", "engine", "service", "converter"))
    processing_mode = pick_first_scalar(payload, ("processingMode", "processing_mode"))

    if page_count:
        lines.append(f"> 页数：{page_count}")
    if parser_name:
        lines.append(f"> 解析器：{parser_name}")
    if processing_mode:
        lines.append(f"> 处理模式：{processing_mode}")
    return "\n".join(lines)


def render_markdown_document(
    *,
    title: str,
    file_path: Path,
    file_kind: str,
    mime: str,
    summary: str,
    key_points: list[str],
    body: str,
    content_blocks,
    raw_source_text: str,
    payload,
) -> dict:
    metadata = build_metadata_lines(file_path, file_kind, mime, payload)
    rendered = render_document(
        title=title,
        source_platform="本地文件",
        source_url=file_path.name,
        summary=summary,
        key_points=key_points,
        source_text=body.strip(),
        content_blocks=content_blocks,
        raw_source_text=raw_source_text,
    )
    markdown = rendered["markdown"].strip()
    lines = markdown.splitlines()
    if lines and lines[0].startswith("# "):
        remaining = lines[1:]
        while remaining and not remaining[0].strip():
            remaining = remaining[1:]
        while remaining and remaining[0].startswith("> "):
            remaining = remaining[1:]
        while remaining and not remaining[0].strip():
            remaining = remaining[1:]
        markdown = "\n".join([lines[0], "", metadata, "", *remaining]).strip() + "\n"
    else:
        markdown = f"# {title}\n\n{metadata}\n\n{markdown}\n"
    return {
        "template_name": rendered["template_name"],
        "summary": rendered["summary"],
        "key_points": rendered["key_points"],
        "content_blocks": rendered["content_blocks"],
        "markdown": markdown,
    }


def read_text_file(path: Path) -> tuple[str, str]:
    raw = path.read_bytes()
    for encoding in ("utf-8", "utf-8-sig", "gb18030", "gbk", "big5"):
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace"), "utf-8-replace"


def truncate_text(text: str, limit: int = 12000) -> str:
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n\n[内容过长，已截断]"


def strip_html_to_text(html_text: str) -> str:
    cleaned = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", html_text)
    cleaned = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", cleaned)
    cleaned = re.sub(r"(?is)<noscript[^>]*>.*?</noscript>", " ", cleaned)
    cleaned = re.sub(r"(?is)<[^>]+>", " ", cleaned)
    return normalize_space(html.unescape(cleaned))


def markdown_table(rows: list[list[str]], headers: list[str] | None = None) -> str:
    if not rows and not headers:
        return ""

    if headers is None and rows:
        headers = rows[0]
        rows = rows[1:]
    headers = headers or []
    if not headers:
        return ""

    def clean_cell(value: str) -> str:
        return normalize_space(value).replace("|", "\\|") or " "

    header_line = "| " + " | ".join(clean_cell(cell) for cell in headers) + " |"
    separator = "| " + " | ".join("---" for _ in headers) + " |"
    body_lines = []
    for row in rows:
        padded = list(row[: len(headers)]) + [""] * max(0, len(headers) - len(row))
        body_lines.append("| " + " | ".join(clean_cell(cell) for cell in padded[: len(headers)]) + " |")
    return "\n".join([header_line, separator, *body_lines]) if body_lines else "\n".join([header_line, separator])


def parse_text_file_locally(path: Path) -> dict:
    suffix = path.suffix.lower()
    text, encoding = read_text_file(path)
    text = text.replace("\r\n", "\n")
    title = path.stem

    if suffix in {".md", ".markdown"}:
        markdown_content = truncate_text(text)
        plain_text = strip_markdown(markdown_content)
        key_points = build_key_points(plain_text)
        return {
            "ok": True,
            "resultCode": 1,
            "data": {
                "title": title,
                "markdown": markdown_content,
                "text": plain_text,
                "keyPoints": key_points,
                "parser": "local_text_parser",
                "processingMode": "local_text",
                "encoding": encoding,
            },
        }

    if suffix in {".html", ".htm"}:
        title_match = re.search(r"<title[^>]*>(.*?)</title>", text, re.IGNORECASE | re.DOTALL)
        html_title = normalize_space(html.unescape(re.sub(r"<[^>]+>", " ", title_match.group(1)))) if title_match else title
        plain_text = truncate_text(strip_html_to_text(text))
        key_points = build_key_points(plain_text)
        return {
            "ok": True,
            "resultCode": 1,
            "data": {
                "title": html_title or title,
                "text": plain_text,
                "keyPoints": key_points,
                "parser": "local_html_parser",
                "processingMode": "local_text",
                "encoding": encoding,
            },
        }

    if suffix == ".json":
        try:
            payload = json.loads(text)
            pretty = json.dumps(payload, ensure_ascii=False, indent=2)
            markdown_content = f"## JSON 内容\n```json\n{truncate_text(pretty, 14000)}\n```"
            keys = list(payload.keys())[:5] if isinstance(payload, dict) else []
            key_points = [f"顶层字段：{key}" for key in keys] if keys else build_key_points(pretty)
        except Exception:
            pretty = truncate_text(text)
            markdown_content = f"## JSON 原文\n```json\n{pretty}\n```"
            key_points = build_key_points(pretty)
        return {
            "ok": True,
            "resultCode": 1,
            "data": {
                "title": title,
                "markdown": markdown_content,
                "text": truncate_text(pretty),
                "keyPoints": key_points,
                "parser": "local_json_parser",
                "processingMode": "local_text",
                "encoding": encoding,
            },
        }

    if suffix in {".csv", ".tsv"}:
        delimiter = "\t" if suffix == ".tsv" else ","
        reader = csv.reader(text.splitlines(), delimiter=delimiter)
        rows = []
        for row in reader:
            rows.append([cell.strip() for cell in row[:MAX_TABLE_COLS]])
            if len(rows) >= MAX_TABLE_ROWS + 1:
                break
        table = markdown_table(rows) if rows else ""
        plain_text = truncate_text(text)
        key_points = build_key_points(plain_text)
        markdown_content = "## 表格预览\n" + (table or "_空表格或无法读取表格内容_")
        if len(rows) > MAX_TABLE_ROWS:
            markdown_content += "\n\n> 表格内容已截断预览。"
        return {
            "ok": True,
            "resultCode": 1,
            "data": {
                "title": title,
                "markdown": markdown_content,
                "text": plain_text,
                "keyPoints": key_points,
                "parser": "local_table_parser",
                "processingMode": "local_text",
                "encoding": encoding,
            },
        }

    if suffix == ".xml":
        try:
            root = ET.fromstring(text)
            plain_text = truncate_text(" ".join(segment.strip() for segment in root.itertext() if normalize_space(segment)))
            key_points = [f"根节点：{root.tag}"] + build_key_points(plain_text)[:2]
        except Exception:
            plain_text = truncate_text(text)
            key_points = build_key_points(plain_text)
        return {
            "ok": True,
            "resultCode": 1,
            "data": {
                "title": title,
                "text": plain_text,
                "keyPoints": key_points,
                "parser": "local_xml_parser",
                "processingMode": "local_text",
                "encoding": encoding,
            },
        }

    plain_text = truncate_text(text)
    return {
        "ok": True,
        "resultCode": 1,
        "data": {
            "title": title,
            "text": plain_text,
            "keyPoints": build_key_points(plain_text),
            "parser": "local_text_parser",
            "processingMode": "local_text",
            "encoding": encoding,
        },
    }


def parse_docx_locally(path: Path) -> dict | None:
    try:
        with zipfile.ZipFile(path) as archive:
            document_xml = archive.read("word/document.xml")
    except Exception:
        return None

    try:
        root = ET.fromstring(document_xml)
    except Exception:
        return None

    paragraphs = []
    for paragraph in root.findall(".//w:p", NS):
        texts = [node.text for node in paragraph.findall(".//w:t", NS) if node.text]
        joined = "".join(texts).strip()
        if joined:
            paragraphs.append(joined)

    if not paragraphs:
        return None

    text = truncate_text("\n\n".join(paragraphs))
    return {
        "ok": True,
        "resultCode": 1,
        "data": {
            "title": path.stem,
            "text": text,
            "keyPoints": build_key_points(text),
            "pageCount": len(paragraphs),
            "parser": "local_docx_parser",
            "processingMode": "local_office",
        },
    }


def parse_pptx_locally(path: Path) -> dict | None:
    try:
        with zipfile.ZipFile(path) as archive:
            slide_names = sorted(name for name in archive.namelist() if name.startswith("ppt/slides/slide") and name.endswith(".xml"))
            sections = []
            for index, slide_name in enumerate(slide_names, start=1):
                root = ET.fromstring(archive.read(slide_name))
                texts = [node.text.strip() for node in root.findall(".//a:t", NS) if node.text and node.text.strip()]
                if texts:
                    sections.append({
                        "title": f"第 {index} 页",
                        "text": "\n".join(texts),
                    })
    except Exception:
        return None

    if not sections:
        return None

    full_text = truncate_text("\n\n".join(section["text"] for section in sections))
    return {
        "ok": True,
        "resultCode": 1,
        "data": {
            "title": path.stem,
            "text": full_text,
            "sections": sections,
            "keyPoints": build_key_points(full_text),
            "pageCount": len(sections),
            "parser": "local_pptx_parser",
            "processingMode": "local_office",
        },
    }


def parse_xlsx_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    try:
        root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    except Exception:
        return []

    strings = []
    for item in root.findall(".//ss:si", NS):
        text = "".join(node.text or "" for node in item.findall(".//ss:t", NS))
        strings.append(text)
    return strings


def parse_xlsx_sheet_names(archive: zipfile.ZipFile) -> list[str]:
    try:
        root = ET.fromstring(archive.read("xl/workbook.xml"))
    except Exception:
        return []
    names = []
    for sheet in root.findall(".//ss:sheets/ss:sheet", NS):
        name = sheet.attrib.get("name", "").strip()
        if name:
            names.append(name)
    return names


def parse_xlsx_locally(path: Path) -> dict | None:
    try:
        with zipfile.ZipFile(path) as archive:
            shared_strings = parse_xlsx_shared_strings(archive)
            sheet_names = parse_xlsx_sheet_names(archive)
            sheet_files = sorted(
                name for name in archive.namelist()
                if name.startswith("xl/worksheets/sheet") and name.endswith(".xml")
            )
            sections = []
            for index, sheet_file in enumerate(sheet_files, start=1):
                root = ET.fromstring(archive.read(sheet_file))
                rows = []
                for row in root.findall(".//ss:sheetData/ss:row", NS):
                    values = []
                    for cell in row.findall("ss:c", NS):
                        cell_type = cell.attrib.get("t")
                        value_node = cell.find("ss:v", NS)
                        value = value_node.text if value_node is not None and value_node.text else ""
                        if cell_type == "s" and value.isdigit():
                            idx = int(value)
                            value = shared_strings[idx] if 0 <= idx < len(shared_strings) else value
                        values.append(value)
                    if any(normalize_space(cell) for cell in values):
                        rows.append(values[:MAX_TABLE_COLS])
                    if len(rows) >= MAX_TABLE_ROWS + 1:
                        break

                if not rows:
                    continue

                table = markdown_table(rows)
                section_title = sheet_names[index - 1] if index - 1 < len(sheet_names) else f"Sheet {index}"
                sections.append({
                    "title": section_title,
                    "markdown": table or "_无法生成表格预览_",
                })
    except Exception:
        return None

    if not sections:
        return None

    combined_markdown = "\n\n".join(
        f"### {section['title']}\n\n{section['markdown']}" for section in sections
    )
    combined_text = truncate_text(strip_markdown(combined_markdown))
    return {
        "ok": True,
        "resultCode": 1,
        "data": {
            "title": path.stem,
            "markdown": combined_markdown,
            "text": combined_text,
            "sections": sections,
            "keyPoints": build_key_points(combined_text),
            "pageCount": len(sections),
            "parser": "local_xlsx_parser",
            "processingMode": "local_office",
        },
    }


def parse_local_file(path: Path) -> tuple[dict | None, str]:
    suffix = path.suffix.lower()
    if suffix in TEXT_EXTENSIONS:
        return parse_text_file_locally(path), "local_text"
    if suffix == ".docx":
        return parse_docx_locally(path), "local_office"
    if suffix == ".pptx":
        return parse_pptx_locally(path), "local_office"
    if suffix == ".xlsx":
        return parse_xlsx_locally(path), "local_office"
    return None, "api"


def local_payload_is_usable(payload: dict | None, *, minimum_length: int) -> bool:
    if not payload or not is_success_payload(payload):
        return False
    data = extract_result_payload(payload)
    content = (
        pick_first_string(
            data,
            (
                "markdown",
                "md",
                "markdownContent",
                "contentMarkdown",
                "outputMarkdown",
                "resultMarkdown",
                "text",
                "content",
                "body",
                "plainText",
                "plain_text",
                "extractedText",
                "extracted_text",
                "source_text",
            ),
        )
        or ""
    )
    sections = pick_first_list(data, ("sections", "pages", "chunks", "blocks", "paragraphs"))
    if sections and not content:
        content = build_sections_markdown(sections)
    return len(strip_markdown(content)) >= minimum_length


def should_call_api_directly(path: Path) -> bool:
    suffix = path.suffix.lower()
    if suffix in API_DIRECT_EXTENSIONS:
        return True
    if suffix in IMAGE_EXTENSIONS:
        return True
    if suffix not in TEXT_EXTENSIONS and suffix not in LOCAL_LIGHT_OFFICE_EXTENSIONS:
        return True
    return False


def build_output(
    *,
    payload: dict,
    file_path: Path,
    file_kind: str,
    mime: str,
    args: argparse.Namespace,
    processing_mode: str,
    used_api_fallback: bool,
    fallback_reason: str = "",
) -> dict:
    data = extract_result_payload(payload)
    title = sanitize_title(file_path, payload)
    summary = pick_first_string(data, ("summary", "abstract", "description", "desc", "brief"))
    markdown_content = pick_first_string(
        data,
        ("markdown", "md", "markdownContent", "contentMarkdown", "outputMarkdown", "resultMarkdown"),
    )
    text_content = pick_first_string(
        data,
        (
            "text",
            "content",
            "body",
            "plainText",
            "plain_text",
            "extractedText",
            "extracted_text",
            "source_text",
            "ocr_text",
        ),
    )
    sections = pick_first_list(data, ("sections", "pages", "chunks", "blocks", "paragraphs"))
    key_points = normalize_key_points(pick_first_list(data, ("keyPoints", "key_points", "highlights")))
    content_for_summary = markdown_content or text_content or ""
    if not key_points:
        key_points = build_key_points(content_for_summary)
    key_points = polish_key_points(key_points, fallback_text=content_for_summary)
    final_summary = polish_summary(
        build_summary(summary, key_points, content_for_summary),
        key_points,
        fallback_text=content_for_summary,
        prefix="本地文件内容",
    )
    sections_markdown = build_sections_markdown(sections)
    organized_body = organize_body(markdown_content or text_content or "", sections_markdown)
    content_blocks = build_content_blocks_from_sections(sections)
    if not content_blocks:
        content_blocks = build_content_blocks_from_text(markdown_content or text_content or "")
    rendered = render_markdown_document(
        title=title,
        file_path=file_path,
        file_kind=file_kind,
        mime=mime,
        summary=final_summary,
        key_points=key_points,
        body=organized_body,
        content_blocks=content_blocks,
        raw_source_text=text_content or "",
        payload=data,
    )

    result = {
        "ok": True,
        "source_type": "uploaded_file",
        "input": str(file_path),
        "title": title,
        "summary": final_summary,
        "key_points": key_points,
        "content_blocks": content_blocks,
        "file_kind": file_kind,
        "extension": file_path.suffix.lower(),
        "mime": mime,
        "service_has_markdown": bool(markdown_content),
        "service_has_text": bool(text_content),
        "processing_mode": processing_mode,
        "used_api_fallback": used_api_fallback,
        "document_template": rendered["template_name"],
    }
    if fallback_reason:
        result["fallback_reason"] = fallback_reason

    result["summary"] = rendered["summary"]
    result["key_points"] = rendered["key_points"]
    result["content_blocks"] = rendered["content_blocks"]

    result.update(
        build_document_result(
            markdown=rendered["markdown"],
            title=title,
            source_type="uploaded_file",
            ingest=args.ingest,
            explicit_app_key=args.app_key,
            sender_id=args.sender_id,
            account_id=args.account_id,
            context_json=args.context_json,
        )
    )
    return result


def main() -> int:
    args = parse_args()
    path = Path(args.file_path).expanduser()

    if not path.exists():
        print(json.dumps({
            "ok": False,
            "source_type": "uploaded_file",
            "input": str(path),
            "error": "文件不存在",
        }, ensure_ascii=False))
        return 1

    if not path.is_file():
        print(json.dumps({
            "ok": False,
            "source_type": "uploaded_file",
            "input": str(path),
            "error": "目标路径不是文件",
        }, ensure_ascii=False))
        return 1

    file_kind = detect_file_kind(path)
    mime = guess_mime(path)

    try:
        payload = None
        processing_mode = "api"
        used_api_fallback = False
        fallback_reason = ""

        if args.mock_response_file:
            payload = load_mock_payload(args.mock_response_file)
            processing_mode = "api_mock"
        elif should_call_api_directly(path):
            api_url = resolve_api_url(args)
            token = resolve_token(args)
            payload = upload_file_sync(
                api_url=api_url,
                file_path=path,
                token=token,
                header_name=args.header_name,
                timeout_seconds=args.timeout_seconds,
            )
            processing_mode = "api"
        else:
            payload, local_mode = parse_local_file(path)
            processing_mode = local_mode
            minimum_length = 1 if path.suffix.lower() in TEXT_EXTENSIONS else LOCAL_OFFICE_MIN_LENGTH

            if not local_payload_is_usable(payload, minimum_length=minimum_length):
                fallback_reason = f"{local_mode}_insufficient_content"
                api_url = resolve_api_url(args)
                token = resolve_token(args)
                payload = upload_file_sync(
                    api_url=api_url,
                    file_path=path,
                    token=token,
                    header_name=args.header_name,
                    timeout_seconds=args.timeout_seconds,
                )
                processing_mode = "api"
                used_api_fallback = True

        if not is_success_payload(payload):
            print(json.dumps({
                "ok": False,
                "source_type": "uploaded_file",
                "input": str(path),
                "file_kind": file_kind,
                "mime": mime,
                "processing_mode": processing_mode,
                "error": extract_service_message(payload),
            }, ensure_ascii=False))
            return 1

        result = build_output(
            payload=payload,
            file_path=path,
            file_kind=file_kind,
            mime=mime,
            args=args,
            processing_mode=processing_mode,
            used_api_fallback=used_api_fallback,
            fallback_reason=fallback_reason,
        )
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({
            "ok": False,
            "source_type": "uploaded_file",
            "input": str(path),
            "file_kind": file_kind,
            "mime": mime,
            "error": str(exc),
        }, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
