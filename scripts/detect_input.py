#!/usr/bin/env python3
"""Detect input kind for everything-2-markdown."""
from __future__ import annotations

import json
import mimetypes
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse


YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "youtu.be",
}

DOUYIN_HOSTS = {
    "douyin.com",
    "www.douyin.com",
    "v.douyin.com",
}

TOUTIAO_HOSTS = {
    "toutiao.com",
    "www.toutiao.com",
    "m.toutiao.com",
    "ixigua.com",
    "www.ixigua.com",
}

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

URL_PATTERN = re.compile(r"https?://[^\s<>\u3000]+", re.IGNORECASE)
TRAILING_URL_CHARS = " \t\r\n'\"`)]}>,.;:!?。，、！？；：~"
DEFAULT_RESOLVE_TIMEOUT_SECONDS = 10

ISSUE_ACTION_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"提\s*(个)?\s*issue",
        r"提交\s*issue",
        r"创建\s*issue",
        r"开\s*(个)?\s*issue",
        r"报\s*(个)?\s*issue",
        r"提\s*(个)?\s*bug",
        r"提交\s*bug",
        r"报\s*(个)?\s*bug",
        r"反馈.*github",
        r"反馈.*仓库",
        r"提.*github",
        r"提.*仓库",
        r"记.*issue",
    )
]

ISSUE_PROBLEM_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\bbug\b",
        r"报错",
        r"错误",
        r"异常",
        r"有问题",
        r"有个问题",
        r"不对",
        r"失败",
        r"失效",
        r"不能用",
        r"不可用",
        r"没反应",
        r"识别错",
        r"路由错",
        r"崩溃",
    )
]


def is_url(value: str) -> bool:
    return bool(re.match(r"^https?://", value or "", re.IGNORECASE))


def clean_candidate_url(value: str) -> str:
    candidate = (value or "").strip()
    while candidate and candidate[-1] in TRAILING_URL_CHARS:
        candidate = candidate[:-1]
    return candidate


def extract_url_from_text(value: str) -> str | None:
    if not value:
        return None

    for match in URL_PATTERN.finditer(value):
        candidate = clean_candidate_url(match.group(0))
        parsed = urlparse(candidate)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            return candidate
    return None


def should_resolve_short_url(url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    path = parsed.path or ""

    if host == "v.douyin.com":
        return True
    if host == "m.toutiao.com" and path.startswith("/is/"):
        return True
    return False


def resolve_short_url(url: str, timeout_seconds: int = DEFAULT_RESOLVE_TIMEOUT_SECONDS) -> dict:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=max(timeout_seconds, 1)) as response:
            final_url = clean_candidate_url(response.geturl())
            return {
                "resolved": bool(final_url and final_url != url),
                "final_url": final_url or url,
            }
    except (urllib.error.HTTPError, urllib.error.URLError, ValueError):
        return {
            "resolved": False,
            "final_url": url,
        }


def classify_url(url: str) -> dict:
    original_url = url
    resolved_from_short_url = False
    if should_resolve_short_url(url):
        resolution = resolve_short_url(url)
        url = resolution.get("final_url") or url
        resolved_from_short_url = bool(resolution.get("resolved"))

    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()

    if host in YOUTUBE_HOSTS:
        result = {
            "ok": True,
            "kind": "youtube_url",
            "route": "scripts/youtube_to_markdown.py",
            "host": host,
            "input": url,
        }
    elif host in DOUYIN_HOSTS:
        result = {
            "ok": True,
            "kind": "douyin_url",
            "route": "scripts/douyin_to_markdown.py",
            "host": host,
            "input": url,
        }
    elif host in TOUTIAO_HOSTS:
        result = {
            "ok": True,
            "kind": "toutiao_url",
            "route": "scripts/toutiao_to_markdown.py",
            "host": host,
            "input": url,
        }
    else:
        result = {
            "ok": True,
            "kind": "generic_url",
            "route": "scripts/url_to_markdown.py",
            "host": host,
            "input": url,
        }

    if resolved_from_short_url:
        result.update(
            {
                "resolved_from_short_url": True,
                "original_short_url": original_url,
            }
        )
    return result


def detect_file_kind(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in TEXT_EXTENSIONS:
        return "text_file"
    if suffix in LOCAL_LIGHT_OFFICE_EXTENSIONS or suffix in API_DIRECT_EXTENSIONS:
        return "office_file"
    if suffix in IMAGE_EXTENSIONS:
        return "image_file"
    return "unknown_file"


def infer_file_processing_strategy(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in TEXT_EXTENSIONS:
        return "local_text"
    if suffix in LOCAL_LIGHT_OFFICE_EXTENSIONS:
        return "local_office_then_api"
    if suffix in API_DIRECT_EXTENSIONS or suffix in IMAGE_EXTENSIONS:
        return "api_direct"
    return "api_direct"


def infer_file_processing_reason(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in TEXT_EXTENSIONS:
        return f"text_extension:{suffix}"
    if suffix in LOCAL_LIGHT_OFFICE_EXTENSIONS:
        return f"local_light_office_extension:{suffix}"
    if suffix in API_DIRECT_EXTENSIONS:
        return f"api_direct_office_extension:{suffix}"
    if suffix in IMAGE_EXTENSIONS:
        return f"image_extension:{suffix}"
    if suffix:
        return f"unknown_extension:{suffix}"
    return "missing_extension"


def classify_file(file_path: str) -> dict:
    path = Path(file_path).expanduser()
    suffix = path.suffix.lower()
    mime, _ = mimetypes.guess_type(str(path))
    strategy = infer_file_processing_strategy(path)
    reason = infer_file_processing_reason(path)

    return {
        "ok": True,
        "kind": "uploaded_file",
        "file_kind": detect_file_kind(path),
        "route": "scripts/file_to_markdown.py",
        "input": str(path),
        "exists": path.exists(),
        "extension": suffix,
        "mime": mime,
        "file_processing_strategy": strategy,
        "file_processing_reason": reason,
        "file_will_call_api_directly": strategy == "api_direct",
    }


def infer_source_type_from_text(value: str) -> str:
    text = value.lower()
    if "youtube" in text or "youtu.be" in text:
        return "youtube_url"
    if "抖音" in value or "douyin" in text:
        return "douyin_url"
    if "头条" in value or "西瓜" in value or "toutiao" in text or "ixigua" in text:
        return "toutiao_url"
    if "上传文件" in value or "本地文件" in value:
        return "uploaded_file"
    if any(
        ext in text
        for ext in (".pdf", ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx", ".png", ".jpg", ".jpeg")
    ):
        return "uploaded_file"
    return ""


def detect_issue_intent(value: str) -> bool:
    if not value:
        return False

    has_action = any(pattern.search(value) for pattern in ISSUE_ACTION_PATTERNS)
    has_problem = any(pattern.search(value) for pattern in ISSUE_PROBLEM_PATTERNS)
    mentions_destination = any(keyword in value.lower() for keyword in ("github", "issue", "仓库"))

    if has_action and (has_problem or mentions_destination):
        return True
    if mentions_destination and has_problem and any(
        keyword in value for keyword in ("帮我", "麻烦", "请", "提", "报", "反馈", "提交", "创建", "开")
    ):
        return True
    return False


def classify_issue_report(value: str) -> dict:
    result = {
        "ok": True,
        "kind": "issue_report",
        "route": "scripts/report_github_issue.py",
        "input": value,
    }

    related_source_type = infer_source_type_from_text(value)
    embedded_url = extract_url_from_text(value)
    if embedded_url:
        related = classify_url(embedded_url)
        result.update(
            {
                "related_url": related.get("input"),
                "related_host": related.get("host"),
                "related_kind": related.get("kind"),
            }
        )
        related_source_type = related.get("kind") or related_source_type

    if related_source_type:
        result["source_type_hint"] = related_source_type

    return result


def classify(value: str, declared_type: str = "") -> dict:
    if declared_type == "file":
        return classify_file(value)

    if detect_issue_intent(value):
        return classify_issue_report(value)

    if is_url(value):
        return classify_url(value)

    embedded_url = extract_url_from_text(value)
    if embedded_url:
        result = classify_url(embedded_url)
        result.update(
            {
                "detected_from_embedded_url": True,
                "original_input": value,
            }
        )
        return result

    if os.path.exists(value):
        return classify_file(value)

    return {
        "ok": True,
        "kind": "plain_text",
        "route": "scripts/text_to_summary.py",
        "input": value,
    }


def main() -> int:
    if len(sys.argv) < 2:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": "usage: detect_input.py <value> [--type file]",
                },
                ensure_ascii=False,
            )
        )
        return 1

    value = sys.argv[1]
    declared_type = ""
    if len(sys.argv) >= 4 and sys.argv[2] == "--type":
        declared_type = sys.argv[3].strip().lower()

    result = classify(value, declared_type=declared_type)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
