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

OFFICE_EXTENSIONS = {
    ".pdf",
    ".doc",
    ".docx",
    ".ppt",
    ".pptx",
    ".xls",
    ".xlsx",
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


def classify_file(file_path: str) -> dict:
    path = Path(file_path).expanduser()
    suffix = path.suffix.lower()
    mime, _ = mimetypes.guess_type(str(path))

    if suffix in TEXT_EXTENSIONS:
        file_kind = "text_file"
    elif suffix in OFFICE_EXTENSIONS:
        file_kind = "office_file"
    elif suffix in IMAGE_EXTENSIONS:
        file_kind = "image_file"
    else:
        file_kind = "unknown_file"

    return {
        "ok": True,
        "kind": "uploaded_file",
        "file_kind": file_kind,
        "route": "scripts/file_to_markdown.py",
        "input": str(path),
        "exists": path.exists(),
        "extension": suffix,
        "mime": mime,
    }


def classify(value: str, declared_type: str = "") -> dict:
    if declared_type == "file":
        return classify_file(value)

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
