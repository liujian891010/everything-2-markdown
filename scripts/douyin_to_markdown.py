#!/usr/bin/env python3
"""Douyin flow for everything-2-markdown.

Phase 1:
- call audio/export-with-asr API
- read asr_text as source content
- build a short intro
- ask the user whether to continue organizing

Phase 2:
- when --organize is passed, render a full markdown document from asr_text
  using references/report-template.md
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
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


API_URL = "https://hk-al-xg-node.mediportal.com.cn/api/open/audio/export-with-asr"
DEFAULT_BEARER_TOKEN = (
    "47a0e299aaea700d6133a9ee3ab17018a56c616ada15ba1f484faec70801169b"
)
SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
TEMPLATE_PATH = SKILL_DIR / "references" / "report-template.md"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert a Douyin URL into a short intro or a full markdown document."
    )
    parser.add_argument("douyin_url", help="Douyin URL")
    parser.add_argument(
        "--organize",
        action="store_true",
        help="Render a full markdown document instead of only returning a short intro",
    )
    parser.add_argument(
        "--token",
        default=os.getenv("DOUYIN_ASR_TOKEN", DEFAULT_BEARER_TOKEN),
        help="Bearer token for the ASR API",
    )
    parser.add_argument(
        "--mock-response-file",
        help="Use a local JSON file instead of calling the remote API",
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


def http_post_json(url: str, payload: dict, headers: dict) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            raw = response.read()
            charset = response.headers.get_content_charset() or "utf-8"
            return json.loads(raw.decode(charset))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"抖音 ASR 请求失败: HTTP {exc.code} {raw}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"抖音 ASR 请求失败: {exc.reason}") from exc


def load_mock_payload(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def pick_first(container: dict, *keys: str) -> str | None:
    for key in keys:
        value = container.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def extract_result_payload(payload: dict) -> dict:
    data = payload.get("data")
    if isinstance(data, dict):
        return data
    return payload


def extract_asr_text(payload: dict) -> str:
    data = extract_result_payload(payload)
    text = pick_first(
        data,
        "asr_text",
        "asrText",
        "text",
        "content",
        "source_text",
        "sourceText",
    )
    if text:
        return text.strip()
    raise RuntimeError("抖音 ASR 接口未返回 asr_text")


def split_sentences(text: str) -> list[str]:
    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized:
        return []
    parts = re.split(r"(?<=[。！？!?；;])\s*", normalized)
    return [part.strip() for part in parts if part.strip()]


def build_key_points(asr_text: str) -> list[str]:
    sentences = split_sentences(asr_text)
    if sentences:
        return sentences[:3]

    compact = re.sub(r"\s+", " ", asr_text).strip()
    if not compact:
        return []

    chunks = [chunk.strip() for chunk in re.split(r"[，,]", compact) if chunk.strip()]
    return chunks[:3] if chunks else [compact[:120]]


def build_summary(key_points: list[str], asr_text: str) -> str:
    cleaned_points = [point.rstrip("。；;!！?？") for point in key_points if point.strip()]

    if cleaned_points:
        if len(cleaned_points) == 1:
            return f"这条抖音内容主要在讲：{cleaned_points[0]}。"
        if len(cleaned_points) == 2:
            return f"这条抖音主要包含两个重点：{cleaned_points[0]}；{cleaned_points[1]}。"
        return (
            f"这条抖音主要围绕以下内容展开："
            f"{cleaned_points[0]}；{cleaned_points[1]}；{cleaned_points[2]}。"
        )

    compact = re.sub(r"\s+", " ", asr_text).strip()
    if not compact:
        return "已完成抖音 ASR 提取，但接口未返回可用正文。"
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
        normalized = re.sub(r"\s+", " ", source_text).strip()
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
        source_platform="抖音",
        source_url=source_url,
        report_date=date.today().isoformat(),
        summary=summary,
        key_points_bullets=bullets_from_key_points(key_points),
        organized_body=organize_source_text(source_text),
    )


def build_output(
    payload: dict,
    douyin_url: str,
    organize: bool,
    args: argparse.Namespace,
) -> dict:
    data = extract_result_payload(payload)
    asr_text = extract_asr_text(payload)
    key_points = polish_key_points(build_key_points(asr_text), fallback_text=asr_text)
    summary = polish_summary(
        build_summary(key_points, asr_text),
        key_points,
        fallback_text=asr_text,
        prefix="这条抖音内容",
    )
    title = pick_first(data, "title", "videoTitle", "name") or "抖音内容整理"

    content_blocks = build_content_blocks_from_text(asr_text)

    result = {
        "ok": True,
        "source_type": "douyin_url",
        "input": douyin_url,
        "title": title,
        "summary": summary,
        "key_points": key_points,
        "content_blocks": content_blocks,
        "source_text_length": len(asr_text),
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
        source_platform="抖音",
        source_url=douyin_url,
        summary=summary,
        key_points=key_points,
        source_text=asr_text,
        content_blocks=content_blocks,
        raw_source_text=asr_text,
    )
    result["summary"] = rendered["summary"]
    result["key_points"] = rendered["key_points"]
    result["content_blocks"] = rendered["content_blocks"]
    result["document_template"] = rendered["template_name"]

    result.update(
        build_document_result(
            markdown=rendered["markdown"],
            title=title,
            source_type="douyin_url",
            ingest=args.ingest,
            explicit_app_key=args.app_key,
            sender_id=args.sender_id,
            account_id=args.account_id,
            context_json=args.context_json,
        )
    )
    return result


def fetch_asr_result(douyin_url: str, token: str) -> dict:
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    return http_post_json(API_URL, {"url": douyin_url}, headers=headers)


def main() -> int:
    args = parse_args()

    try:
        if args.mock_response_file:
            payload = load_mock_payload(args.mock_response_file)
        else:
            payload = fetch_asr_result(args.douyin_url, args.token)

        result = build_output(
            payload,
            args.douyin_url,
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
