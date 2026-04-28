#!/usr/bin/env python3
"""Generic URL flow for everything-2-markdown.

Fallback chain:
1. Tavily Extract API
2. Jina.ai Reader
3. LLM-Reader
4. Raw requests

If extraction succeeds:
- build a short summary first
- ask the user whether to continue organizing

If --organize is passed:
- render a full markdown document using references/report-template.md
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

from docdb_support import build_document_result
from document_renderer import (
    build_content_blocks_from_text,
    polish_key_points,
    polish_summary,
    render_document,
)


TAVILY_EXTRACT_URL = "https://api.tavily.com/extract"
JINA_READER_PREFIX = "https://r.jina.ai/"
LLM_READER_URL = "https://reader.llm.report/api/read"
SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
TEMPLATE_PATH = SKILL_DIR / "references" / "report-template.md"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert a generic URL into a short intro or a full markdown report."
    )
    parser.add_argument("url", help="Generic URL")
    parser.add_argument(
        "--organize",
        action="store_true",
        help="Render a full markdown document instead of only returning a short intro",
    )
    parser.add_argument(
        "--mock-response-file",
        help="Use a local JSON file instead of calling remote extractors",
    )
    parser.add_argument("--app-key", help="Optional appKey used for cms-docdb ingestion")
    parser.add_argument("--sender-id", help="Optional sender_id used to resolve appKey")
    parser.add_argument("--account-id", help="Optional account_id used to resolve appKey")
    parser.add_argument("--context-json", default="", help="Optional auth context JSON")
    parser.add_argument(
        "--ingest",
        action="store_true",
        help="Deprecated: generated markdown documents are uploaded to cms-docdb automatically",
    )
    return parser.parse_args()


def get_config_path() -> Path:
    if os.getenv("OPENCLAW_ROOT"):
        return Path.home() / ".openclaw"
    if os.getenv("HERMES_ROOT"):
        return Path.home() / ".hermes"
    return Path.home() / ".config"


def get_tavily_key() -> str | None:
    config_path = get_config_path() / "link-archivist-config.json"
    if config_path.exists():
        try:
            cfg = json.loads(config_path.read_text(encoding="utf-8"))
            key = cfg.get("tavily_api_key")
            if key:
                return key
        except Exception:
            pass
    return os.getenv("TAVILY_API_KEY")


def http_post_json(url: str, payload: dict, headers: dict | None = None, timeout: int = 30) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers or {"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            charset = response.headers.get_content_charset() or "utf-8"
            return json.loads(raw.decode(charset))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {raw}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"URL error: {exc.reason}") from exc


def http_get_text(url: str, headers: dict | None = None, timeout: int = 20) -> str:
    request = urllib.request.Request(url, headers=headers or {}, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            charset = response.headers.get_content_charset() or "utf-8"
            return raw.decode(charset, errors="replace")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {raw}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"URL error: {exc.reason}") from exc


def normalize_space(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def is_good_content(text: str | None, min_length: int = 120) -> bool:
    normalized = normalize_space(text)
    if len(normalized) < min_length:
        return False
    noisy_markers = ["访问过于频繁", "captcha", "verify you are human"]
    lower = normalized.lower()
    return not any(marker in lower for marker in noisy_markers)


def fetch_via_tavily(url: str) -> dict | None:
    api_key = get_tavily_key()
    if not api_key:
        return None

    try:
        payload = http_post_json(
            TAVILY_EXTRACT_URL,
            {"api_key": api_key, "urls": [url]},
            headers={"Content-Type": "application/json"},
            timeout=30,
        )
    except Exception:
        return None

    results = payload.get("results")
    if not isinstance(results, list) or not results:
        return None

    first = results[0] if isinstance(results[0], dict) else {}
    content = (
        first.get("raw_content")
        or first.get("markdown")
        or first.get("content")
        or ""
    )
    title = first.get("title") or ""

    if not is_good_content(content):
        return None

    return {
        "extractor_used": "tavily_extract",
        "title": title,
        "content": content,
    }


def fetch_via_jina(url: str) -> dict | None:
    reader_url = f"{JINA_READER_PREFIX}{url}"
    headers = {
        "Accept": "text/markdown",
        "X-Target-Selector": "article, main, .article, .content, .main",
    }
    try:
        content = http_get_text(reader_url, headers=headers, timeout=20)
    except Exception:
        return None

    if not is_good_content(content):
        return None

    title = extract_title_from_markdown(content) or extract_title_from_text(content)
    return {
        "extractor_used": "jina_reader",
        "title": title,
        "content": content,
    }


def fetch_via_llm_reader(url: str) -> dict | None:
    reader_url = f"{LLM_READER_URL}?url={urllib.parse.quote(url, safe='')}"
    try:
        raw = http_get_text(reader_url, timeout=20)
        payload = json.loads(raw)
    except Exception:
        return None

    content = ""
    title = ""
    if isinstance(payload, dict):
        content = (
            payload.get("markdown")
            or payload.get("content")
            or payload.get("text")
            or ""
        )
        title = payload.get("title") or ""

    if not is_good_content(content):
        return None

    return {
        "extractor_used": "llm_reader",
        "title": title or extract_title_from_markdown(content) or extract_title_from_text(content),
        "content": content,
    }


def extract_title_from_html(html_text: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", html_text, re.IGNORECASE | re.DOTALL)
    if not match:
        return ""
    return normalize_space(html.unescape(re.sub(r"<[^>]+>", " ", match.group(1))))


def strip_html_tags(text: str) -> str:
    cleaned = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", text)
    cleaned = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", cleaned)
    cleaned = re.sub(r"(?is)<noscript[^>]*>.*?</noscript>", " ", cleaned)
    cleaned = re.sub(r"(?is)<svg[^>]*>.*?</svg>", " ", cleaned)
    cleaned = re.sub(r"(?is)<[^>]+>", " ", cleaned)
    return normalize_space(html.unescape(cleaned))


def extract_article_from_ld_json(html_text: str) -> tuple[str, str]:
    scripts = re.findall(
        r'(?is)<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html_text,
    )
    for script in scripts:
        try:
            payload = json.loads(html.unescape(script))
        except Exception:
            continue

        objects = payload if isinstance(payload, list) else [payload]
        for obj in objects:
            if not isinstance(obj, dict):
                continue
            title = normalize_space(
                obj.get("headline") or obj.get("name") or obj.get("title") or ""
            )
            body = normalize_space(
                obj.get("articleBody") or obj.get("description") or obj.get("text") or ""
            )
            if is_good_content(body, min_length=80):
                return title, body
    return "", ""


def extract_article_block(html_text: str) -> str:
    patterns = [
        r"(?is)<article[^>]*>(.*?)</article>",
        r'(?is)<main[^>]*>(.*?)</main>',
        r'(?is)<div[^>]+class=["\'][^"\']*(article|content|main|post|entry)[^"\']*["\'][^>]*>(.*?)</div>',
    ]
    for pattern in patterns:
        match = re.search(pattern, html_text)
        if not match:
            continue
        block = match.group(match.lastindex or 1)
        text = strip_html_tags(block)
        if is_good_content(text, min_length=80):
            return text
    return ""


def extract_title_from_markdown(content: str) -> str:
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip()
    return ""


def extract_title_from_text(content: str) -> str:
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    return lines[0][:80] if lines else ""


def fetch_via_raw_requests(url: str) -> dict | None:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    try:
        html_text = http_get_text(url, headers=headers, timeout=15)
    except Exception:
        return None

    title, body = extract_article_from_ld_json(html_text)
    if not body:
        body = extract_article_block(html_text)
    if not title:
        title = extract_title_from_html(html_text)
    if not body:
        body = strip_html_tags(html_text)

    if not is_good_content(body):
        return None

    return {
        "extractor_used": "raw_requests",
        "title": title,
        "content": body,
    }


def extract_content(url: str, mock_response_file: str | None = None) -> dict | None:
    if mock_response_file:
        payload = json.loads(Path(mock_response_file).read_text(encoding="utf-8"))
        return {
            "extractor_used": payload.get("extractor_used", "mock"),
            "title": payload.get("title", ""),
            "content": payload.get("content", ""),
        }

    for fetcher in (
        fetch_via_tavily,
        fetch_via_jina,
        fetch_via_llm_reader,
        fetch_via_raw_requests,
    ):
        result = fetcher(url)
        if result and is_good_content(result.get("content")):
            return result
    return None


def split_sentences(text: str) -> list[str]:
    normalized = normalize_space(text)
    if not normalized:
        return []
    parts = re.split(r"(?<=[。！？!?；;])\s*", normalized)
    return [part.strip() for part in parts if part.strip()]


def build_key_points(content: str) -> list[str]:
    sentences = split_sentences(content)
    if sentences:
        return sentences[:3]
    chunks = [chunk.strip() for chunk in re.split(r"[，,]", normalize_space(content)) if chunk.strip()]
    return chunks[:3] if chunks else []


def build_summary(key_points: list[str], content: str) -> str:
    cleaned_points = [point.rstrip("。；;!！?？") for point in key_points if point.strip()]
    if cleaned_points:
        if len(cleaned_points) == 1:
            return f"这个网页内容主要在讲：{cleaned_points[0]}。"
        if len(cleaned_points) == 2:
            return f"这个网页主要包含两个重点：{cleaned_points[0]}；{cleaned_points[1]}。"
        return (
            f"这个网页主要围绕以下内容展开："
            f"{cleaned_points[0]}；{cleaned_points[1]}；{cleaned_points[2]}。"
        )

    compact = normalize_space(content)
    if not compact:
        return "已完成网页抓取流程，但未获取到可用正文。"
    return compact[:150] + ("..." if len(compact) > 150 else "")


def organize_source_text(source_text: str) -> str:
    lines = [line.strip() for line in source_text.splitlines()]
    paragraphs = []
    bucket = []

    for line in lines:
        if not line:
            if bucket:
                paragraphs.append(" ".join(bucket))
                bucket = []
            continue
        bucket.append(line)

    if bucket:
        paragraphs.append(" ".join(bucket))

    if not paragraphs:
        normalized = normalize_space(source_text)
        return normalized or "原始文本为空。"

    return "\n\n".join(paragraphs)


def bullets_from_key_points(key_points: list[str]) -> str:
    if not key_points:
        return "- 暂无明确关键要点"
    return "\n".join(f"- {point}" for point in key_points)


def load_template() -> str:
    if not TEMPLATE_PATH.exists():
        raise RuntimeError(f"模板不存在: {TEMPLATE_PATH}")
    content = TEMPLATE_PATH.read_text(encoding="utf-8")
    start = content.find("```markdown")
    end = content.rfind("```")
    if start == -1 or end == -1 or end <= start:
        raise RuntimeError("report-template.md 缺少 markdown 模板代码块")
    return content[start + len("```markdown"):end].strip()


def render_markdown_document(
    *,
    title: str,
    source_url: str,
    summary: str,
    key_points: list[str],
    source_text: str,
) -> str:
    template = load_template()
    return template.format(
        title=title,
        source_platform="网页",
        source_url=source_url,
        report_date=date.today().isoformat(),
        summary=summary,
        key_points_bullets=bullets_from_key_points(key_points),
        organized_body=organize_source_text(source_text),
    )


def build_output(
    extracted: dict,
    url: str,
    organize: bool,
    args: argparse.Namespace,
) -> dict:
    content = extracted.get("content", "")
    title = extracted.get("title") or "网页内容整理"
    key_points = polish_key_points(build_key_points(content), fallback_text=content)
    summary = polish_summary(
        build_summary(key_points, content),
        key_points,
        fallback_text=content,
        prefix="这个网页内容",
    )

    content_blocks = build_content_blocks_from_text(content)

    result = {
        "ok": True,
        "source_type": "generic_url",
        "input": url,
        "title": title,
        "summary": summary,
        "key_points": key_points,
        "content_blocks": content_blocks,
        "source_text_length": len(content),
        "extractor_used": extracted.get("extractor_used"),
    }

    if not organize:
        result.update(
            {
                "phase": "await_user_confirmation",
                "intro_markdown": (
                    f"**{title}**\n\n{summary}"
                    + (f"\n\n{bullets_from_key_points(key_points)}" if key_points else "")
                ),
                "question": "是否需要我继续按模板整理成正式 Markdown 报告？",
                "next_action": "rerun with --organize after user confirmation",
            }
        )
        return result

    rendered = render_document(
        title=title,
        source_platform="网页",
        source_url=url,
        summary=summary,
        key_points=key_points,
        source_text=content,
        content_blocks=content_blocks,
        raw_source_text=content,
    )
    result["summary"] = rendered["summary"]
    result["key_points"] = rendered["key_points"]
    result["content_blocks"] = rendered["content_blocks"]
    result["document_template"] = rendered["template_name"]

    result.update(
        build_document_result(
            markdown=rendered["markdown"],
            title=title,
            source_type="generic_url",
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

    try:
        extracted = extract_content(args.url, args.mock_response_file)
        if not extracted or not is_good_content(extracted.get("content")):
            print(json.dumps({
                "ok": False,
                "source_type": "generic_url",
                "input": args.url,
                "error": "没有成功抓取内容",
            }, ensure_ascii=False))
            return 1

        result = build_output(
            extracted,
            args.url,
            organize=args.organize,
            args=args,
        )
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
