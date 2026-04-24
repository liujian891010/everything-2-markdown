#!/usr/bin/env python3
"""Create a GitHub issue for everything-2-markdown problems."""
from __future__ import annotations

import argparse
import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone


DEFAULT_REPO = "liujian891010/everything-2-markdown"
DEFAULT_API_BASE = "https://api.github.com"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a GitHub issue for a user-reported problem."
    )
    parser.add_argument(
        "problem",
        nargs="?",
        help="Short problem description or raw user feedback text",
    )
    parser.add_argument("--problem-file", help="Read problem description from a file")
    parser.add_argument(
        "--repo",
        default=os.getenv("GITHUB_ISSUE_REPO", DEFAULT_REPO),
        help="GitHub repository in owner/name format",
    )
    parser.add_argument(
        "--api-base",
        default=os.getenv("GITHUB_API_BASE", DEFAULT_API_BASE),
        help="GitHub API base URL",
    )
    parser.add_argument(
        "--token",
        default=os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN") or "",
        help="GitHub token with repo/issues write permission",
    )
    parser.add_argument("--title", help="Explicit issue title")
    parser.add_argument("--labels", nargs="*", default=[], help="Optional GitHub labels")
    parser.add_argument("--source-type", default="", help="Related source type")
    parser.add_argument("--input-value", default="", help="Original input that caused the issue")
    parser.add_argument("--expected", default="", help="Expected behavior")
    parser.add_argument("--actual", default="", help="Actual behavior")
    parser.add_argument("--error", default="", help="Error message or stack snippet")
    parser.add_argument("--env", default="", help="Runtime environment note")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only print the issue payload without calling GitHub",
    )
    return parser.parse_args()


def normalize_space(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def load_problem_text(args: argparse.Namespace) -> str:
    if args.problem_file:
        with open(args.problem_file, "r", encoding="utf-8") as handle:
            return handle.read()
    return args.problem or ""


def build_title(problem_text: str, explicit_title: str | None, source_type: str) -> str:
    if explicit_title and normalize_space(explicit_title):
        return explicit_title.strip()

    compact = normalize_space(problem_text)
    prefix = "[Bug]"
    if source_type:
        prefix = f"[Bug][{source_type}]"
    if not compact:
        return f"{prefix} User reported issue"
    short = compact[:72]
    return f"{prefix} {short}"


def fenced_block(text: str, info: str = "") -> str:
    content = text.strip() if text else ""
    if not content:
        content = "(empty)"
    fence = "```"
    return f"{fence}{info}\n{content}\n{fence}"


def build_body(*, problem_text: str, args: argparse.Namespace) -> str:
    lines = [
        "## Summary",
        problem_text.strip() or "User reported a problem, but no extra description was provided.",
        "",
        "## Context",
        f"- Reported at: {datetime.now(timezone.utc).isoformat()}",
        f"- Source type: {args.source_type or 'unknown'}",
        f"- Environment: {args.env or 'not provided'}",
    ]

    if args.expected:
        lines.extend(["", "## Expected", args.expected.strip()])
    if args.actual:
        lines.extend(["", "## Actual", args.actual.strip()])
    if args.error:
        lines.extend(["", "## Error", fenced_block(args.error, "text")])
    if args.input_value:
        lines.extend(["", "## Input", fenced_block(args.input_value, "text")])

    lines.extend(
        [
            "",
            "## Notes",
            "- This issue was generated from in-product user feedback.",
        ]
    )
    return "\n".join(lines).strip()


def validate_repo(repo: str) -> str:
    compact = normalize_space(repo)
    if not re.match(r"^[^/\s]+/[^/\s]+$", compact):
        raise RuntimeError("repo must be in owner/name format")
    return compact


def build_issue_payload(problem_text: str, args: argparse.Namespace) -> dict:
    title = build_title(problem_text, args.title, args.source_type)
    body = build_body(problem_text=problem_text, args=args)
    payload = {
        "title": title,
        "body": body,
    }
    labels = [label for label in args.labels if normalize_space(label)]
    if labels:
        payload["labels"] = labels
    return payload


def build_missing_token_result(*, repo: str, payload: dict) -> dict:
    return {
        "ok": False,
        "needs_user_token": True,
        "repo": repo,
        "question": (
            "要帮你提交 GitHub issue，需要一个有该仓库 issue 写权限的 GitHub token。"
            "请把 token 发我，或先设置 GITHUB_TOKEN / GH_TOKEN。"
        ),
        "payload": payload,
    }


def create_issue(*, repo: str, api_base: str, token: str, payload: dict) -> dict:
    url = f"{api_base.rstrip('/')}/repos/{repo}/issues"
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "User-Agent": "everything-2-markdown-issue-reporter",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read()
            charset = response.headers.get_content_charset() or "utf-8"
            return json.loads(raw.decode(charset))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub issue creation failed: HTTP {exc.code} {raw}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"GitHub issue creation failed: {exc.reason}") from exc


def main() -> int:
    args = parse_args()
    problem_text = load_problem_text(args)
    if not normalize_space(problem_text) and not normalize_space(args.error):
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": "usage: report_github_issue.py <problem> | --problem-file <path>",
                },
                ensure_ascii=False,
            )
        )
        return 1

    try:
        repo = validate_repo(args.repo)
        payload = build_issue_payload(problem_text, args)

        if args.dry_run:
            print(
                json.dumps(
                    {
                        "ok": True,
                        "mode": "dry_run",
                        "repo": repo,
                        "payload": payload,
                    },
                    ensure_ascii=False,
                )
            )
            return 0

        if not normalize_space(args.token):
            print(json.dumps(build_missing_token_result(repo=repo, payload=payload), ensure_ascii=False))
            return 1

        issue = create_issue(
            repo=repo,
            api_base=args.api_base,
            token=args.token,
            payload=payload,
        )
        print(
            json.dumps(
                {
                    "ok": True,
                    "mode": "created",
                    "repo": repo,
                    "issue_number": issue.get("number"),
                    "issue_url": issue.get("html_url"),
                    "title": issue.get("title"),
                },
                ensure_ascii=False,
            )
        )
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
