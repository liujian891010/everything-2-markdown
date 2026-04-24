#!/usr/bin/env python3
"""YouTube flow for everything-2-markdown.

Phase 1:
- call video2markdown parse API with token
- poll until success
- build a short intro from key_points
- ask the user whether to continue organizing

Phase 2:
- when --organize is passed, render a full markdown document from source_text
  using references/report-template.md
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

from docdb_support import build_document_result
from document_renderer import render_document


API_URL = "https://sg-al-cwork-web.mediportal.com.cn/video2markdown/parse"
DEFAULT_TOKEN_HEADER = "access-token"
DEFAULT_TIMEOUT_SECONDS = 300
DEFAULT_POLL_INTERVAL_SECONDS = 5
SUCCESS_STATES = {
    "success",
    "succeeded",
    "done",
    "completed",
    "complete",
    "finished",
    "finish",
}
PENDING_STATES = {
    "pending",
    "processing",
    "running",
    "queued",
    "in_progress",
    "parsing",
    "waiting",
}
FAILURE_STATES = {
    "failed",
    "error",
    "timeout",
    "cancelled",
    "canceled",
}
SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
TEMPLATE_PATH = SKILL_DIR / "references" / "report-template.md"
AUTH_SCRIPT = (
    SKILL_DIR.parent / "cms-auth-skills" / "scripts" / "auth" / "login.py"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert a YouTube URL into a short intro or a full markdown document."
    )
    parser.add_argument("youtube_url", help="YouTube URL")
    parser.add_argument(
        "--organize",
        action="store_true",
        help="Render a full markdown document instead of only returning a short intro",
    )
    parser.add_argument("--token", help="Explicit access token")
    parser.add_argument("--app-key", help="Optional appKey used to resolve token")
    parser.add_argument("--sender-id", help="Optional sender_id used to resolve token")
    parser.add_argument("--account-id", help="Optional account_id used to resolve token")
    parser.add_argument("--context-json", default="", help="Optional auth context JSON")
    parser.add_argument(
        "--header-name",
        default=os.getenv("VIDEO2MARKDOWN_TOKEN_HEADER", DEFAULT_TOKEN_HEADER),
        help="HTTP header name used for token authentication",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="Polling timeout in seconds",
    )
    parser.add_argument(
        "--poll-interval",
        type=int,
        default=DEFAULT_POLL_INTERVAL_SECONDS,
        help="Polling interval in seconds",
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


def extract_video_id(url: str) -> str | None:
    patterns = [
        r"(?:youtube\.com/watch\?.*v=|youtu\.be/|youtube\.com/embed/|youtube\.com/shorts/)([\w-]{11})",
        r"youtube\.com/watch\?.*[\?&]v=([\w-]{11})",
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def resolve_token(args: argparse.Namespace) -> str:
    explicit = (
        args.token
        or os.getenv("XG_USER_TOKEN")
        or os.getenv("ACCESS_TOKEN")
        or os.getenv("VIDEO2MARKDOWN_TOKEN")
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
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"自动获取 token 失败: {detail}")

    token = (result.stdout or "").strip().splitlines()
    token_value = token[-1].strip() if token else ""
    if not token_value:
        raise RuntimeError("自动获取 token 失败: 返回为空")
    return token_value


def http_post_json(url: str, payload: dict, headers: dict) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = response.read()
            charset = response.headers.get_content_charset() or "utf-8"
            return json.loads(raw.decode(charset))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"video2markdown 请求失败: HTTP {exc.code} {raw}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"video2markdown 请求失败: {exc.reason}") from exc


def parse_response_state(payload: dict) -> str:
    candidates = [
        payload.get("status"),
        payload.get("state"),
    ]
    data = payload.get("data")
    if isinstance(data, dict):
        candidates.extend(
            [
                data.get("status"),
                data.get("state"),
                data.get("parseStatus"),
                data.get("taskStatus"),
            ]
        )

    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip().lower()
    return ""


def extract_result_payload(payload: dict) -> dict:
    data = payload.get("data")
    if isinstance(data, dict):
        return data
    return payload


def extract_poll_context(payload: dict) -> dict:
    data = extract_result_payload(payload)
    poll_context = {}
    for key in (
        "taskId",
        "task_id",
        "jobId",
        "job_id",
        "requestId",
        "request_id",
        "id",
    ):
        value = data.get(key)
        if value not in (None, ""):
            poll_context[key] = value
    return poll_context


def has_final_content(payload: dict) -> bool:
    data = extract_result_payload(payload)
    return bool(
        normalize_text(pick_first(data, "source_text", "sourceText", "content", "transcript"))
        or normalize_key_points(data.get("key_points") or data.get("keyPoints"))
    )


def is_success_payload(payload: dict) -> bool:
    state = parse_response_state(payload)
    if state in SUCCESS_STATES:
        return True
    return has_final_content(payload)


def is_pending_payload(payload: dict) -> bool:
    state = parse_response_state(payload)
    if state in PENDING_STATES:
        return True
    return not is_success_payload(payload)


def fail_message(payload: dict) -> str:
    data = extract_result_payload(payload)
    return (
        pick_first(
            data,
            "errorMsg",
            "error_msg",
            "message",
            "msg",
            "detailMsg",
        )
        or payload.get("resultMsg")
        or payload.get("message")
        or "video2markdown 处理失败"
    )


def fetch_parse_result(
    youtube_url: str,
    token: str,
    header_name: str,
    timeout_seconds: int,
    poll_interval: int,
) -> dict:
    headers = {
        header_name: token,
        "Content-Type": "application/json",
    }
    payload = {"url": youtube_url}
    response = http_post_json(API_URL, payload, headers=headers)

    if is_success_payload(response):
        return response

    poll_context = extract_poll_context(response)
    if not poll_context and parse_response_state(response) in FAILURE_STATES:
        raise RuntimeError(fail_message(response))

    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        time.sleep(max(poll_interval, 1))
        poll_payload = {"url": youtube_url, **poll_context}
        response = http_post_json(API_URL, poll_payload, headers=headers)
        if is_success_payload(response):
            return response
        if parse_response_state(response) in FAILURE_STATES:
            raise RuntimeError(fail_message(response))
        poll_context.update(extract_poll_context(response))

    raise RuntimeError(f"video2markdown 处理超时，超过 {timeout_seconds} 秒")


def load_mock_payload(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def pick_first(container: dict, *keys: str) -> str | None:
    for key in keys:
        value = container.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"\s+", " ", value).strip()


def normalize_key_points(value) -> list[str]:
    if not value:
        return []

    items = value if isinstance(value, list) else [value]
    normalized = []
    for item in items:
        if isinstance(item, str):
            text = normalize_text(item)
        elif isinstance(item, dict):
            text = normalize_text(
                pick_first(item, "text", "point", "content", "summary", "title") or ""
            )
        else:
            text = normalize_text(str(item))
        if text:
            normalized.append(text)
    return normalized


def build_summary(key_points: list[str]) -> str:
    if not key_points:
        return "已完成 YouTube 内容解析，但接口未返回明确的关键要点。"

    selected = key_points[:3]
    if len(selected) == 1:
        return f"这段视频的核心内容主要围绕：{selected[0]}。"
    if len(selected) == 2:
        return f"这段视频主要讲了两个重点：{selected[0]}；{selected[1]}。"
    return f"这段视频主要围绕以下几点展开：{selected[0]}；{selected[1]}；{selected[2]}。"


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
        normalized = normalize_text(source_text)
        return normalized or "原始文本为空。"

    return "\n\n".join(paragraphs)


def bullets_from_key_points(key_points: list[str]) -> str:
    if not key_points:
        return "- 暂无明确关键要点"
    return "\n".join(f"- {point}" for point in key_points)


def fenced_source_text(source_text: str) -> str:
    if not source_text.strip():
        return "```text\n暂无原始文本\n```"
    return f"```text\n{source_text.strip()}\n```"


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
) -> dict:
    return render_document(
        title=title,
        source_platform="YouTube",
        source_url=source_url,
        summary=summary,
        key_points=key_points,
        source_text=source_text,
    )


def build_output(
    payload: dict,
    youtube_url: str,
    organize: bool,
    args: argparse.Namespace,
) -> dict:
    data = extract_result_payload(payload)
    key_points = normalize_key_points(data.get("key_points") or data.get("keyPoints"))
    source_text = (
        pick_first(data, "source_text", "sourceText", "content", "transcript") or ""
    )
    title = pick_first(data, "title", "videoTitle", "name") or "YouTube 视频整理"
    summary = build_summary(key_points)

    result = {
        "ok": True,
        "source_type": "youtube_url",
        "input": youtube_url,
        "title": title,
        "summary": summary,
        "key_points": key_points,
        "source_text_length": len(source_text),
    }

    if not organize:
        result.update(
            {
                "phase": "await_user_confirmation",
                "intro_markdown": f"**{title}**\n\n{summary}",
                "question": "是否需要我继续按模板整理成正式 Markdown 文档？",
                "next_action": "rerun with --organize after user confirmation",
            }
        )
        return result

    rendered = render_markdown_document(
        title=title,
        source_url=youtube_url,
        summary=summary,
        key_points=key_points,
        source_text=source_text,
    )
    result["document_template"] = rendered["template_name"]

    result.update(
        build_document_result(
            markdown=rendered["markdown"],
            title=title,
            source_type="youtube_url",
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
        if args.mock_response_file:
            payload = load_mock_payload(args.mock_response_file)
        else:
            token = resolve_token(args)
            payload = fetch_parse_result(
                youtube_url=args.youtube_url,
                token=token,
                header_name=args.header_name,
                timeout_seconds=args.timeout_seconds,
                poll_interval=args.poll_interval,
            )

        result = build_output(
            payload,
            args.youtube_url,
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
