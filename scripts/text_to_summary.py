#!/usr/bin/env python3
"""Summarize plain text or chat logs into one paragraph."""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter

from docdb_support import build_document_result


CHAT_LINE_PATTERNS = [
    re.compile(r"^\s*\[?[0-9]{1,2}:[0-9]{2}(?::[0-9]{2})?\]?\s*([^:：]{1,30})[:：]\s*(.+)$"),
    re.compile(r"^\s*([^:：]{1,30})[:：]\s*(.+)$"),
]
INLINE_CHAT_SPEAKER_PATTERN = re.compile(
    r"(^|[\n。！？!?\.])\s*([^:：\n]{1,20})[:：]\s*"
)
STOPWORDS = {
    "的", "了", "和", "是", "在", "就", "都", "而", "及", "与", "着", "或", "一个", "我们",
    "你们", "他们", "这个", "那个", "然后", "已经", "因为", "所以", "需要", "可以", "一下",
    "进行", "如果", "就是", "没有", "不是", "以及", "并且", "这里", "那个", "这段", "内容",
    "我们", "你", "我", "他", "她", "它", "the", "and", "for", "that", "with", "this",
    "from", "have", "has", "are", "was", "were", "will", "would", "should", "could",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Summarize plain text or chat logs into one paragraph."
    )
    parser.add_argument("text", nargs="?", help="Text input")
    parser.add_argument("--text-file", help="Read input text from a file")
    parser.add_argument(
        "--max-sentences",
        type=int,
        default=3,
        help="Maximum number of source sentences to use when building the summary",
    )
    parser.add_argument("--app-key", help="Optional appKey used for cms-docdb ingestion")
    parser.add_argument("--sender-id", help="Optional sender_id used to resolve appKey")
    parser.add_argument("--account-id", help="Optional account_id used to resolve appKey")
    parser.add_argument("--context-json", default="", help="Optional auth context JSON")
    parser.add_argument(
        "--ingest",
        action="store_true",
        help="Upload the generated summary document to cms-docdb",
    )
    return parser.parse_args()


def load_text(args: argparse.Namespace) -> str:
    if args.text_file:
        with open(args.text_file, "r", encoding="utf-8") as handle:
            return handle.read()
    return args.text or ""


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def is_valid_speaker_name(name: str) -> bool:
    normalized = normalize_space(name)
    if not normalized or len(normalized) > 12:
        return False
    if "http" in normalized.lower() or "/" in normalized or "." in normalized:
        return False
    if re.search(r"\s{2,}", normalized):
        return False
    return bool(re.search(r"[\u4e00-\u9fffA-Za-z]", normalized))


def split_sentences(text: str) -> list[str]:
    prepared = re.sub(r"[\r\n]+", "\n", text)
    chunks = re.split(r"(?<=[。！？!?；;])\s+|\n{2,}", prepared)
    sentences = []
    for chunk in chunks:
        normalized = normalize_space(chunk)
        if normalized:
            sentences.append(normalized)
    return sentences


def detect_chat_lines(text: str) -> list[tuple[str, str]]:
    items: list[tuple[str, str]] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        for pattern in CHAT_LINE_PATTERNS:
            match = pattern.match(line)
            if match:
                speaker = normalize_space(match.group(1))
                message = normalize_space(match.group(2))
                if is_valid_speaker_name(speaker) and message:
                    items.append((speaker, message))
                    break
    inline_items: list[tuple[str, str]] = []
    matches = list(INLINE_CHAT_SPEAKER_PATTERN.finditer(text))
    for index, match in enumerate(matches):
        normalized_speaker = normalize_space(match.group(2))
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        normalized_message = normalize_space(text[start:end])
        if is_valid_speaker_name(normalized_speaker) and normalized_message:
            inline_items.append((normalized_speaker, normalized_message))

    if len(inline_items) >= 2:
        return inline_items
    return items


def is_chat_log(text: str) -> bool:
    chat_lines = detect_chat_lines(text)
    non_empty_lines = [line for line in text.splitlines() if line.strip()]
    if len(chat_lines) >= 3:
        return True
    if len(chat_lines) >= 2 and len(non_empty_lines) <= 2:
        return True
    return bool(non_empty_lines) and len(chat_lines) >= max(2, len(non_empty_lines) // 2)


def tokenize(text: str) -> list[str]:
    tokens = re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z][A-Za-z0-9_-]{2,}", text.lower())
    return [token for token in tokens if token not in STOPWORDS]


def sentence_score(sentence: str, frequencies: Counter[str]) -> int:
    score = 0
    for token in tokenize(sentence):
        score += frequencies[token]
    return score


def top_keywords(text: str, limit: int = 5) -> list[str]:
    frequencies = Counter(tokenize(text))
    return [word for word, _ in frequencies.most_common(limit)]


def summarize_plain_text(text: str, max_sentences: int) -> dict:
    sentences = split_sentences(text)
    if not sentences:
        return {
            "ok": False,
            "error": "没有可总结的文本内容",
        }

    frequencies = Counter(tokenize(text))
    ranked = sorted(
        enumerate(sentences),
        key=lambda item: (sentence_score(item[1], frequencies), -item[0]),
        reverse=True,
    )
    chosen_indexes = sorted(index for index, _ in ranked[:max_sentences])
    chosen = [sentences[index] for index in chosen_indexes]
    summary = " ".join(chosen)
    summary = normalize_space(summary)
    if len(summary) > 220:
        summary = summary[:220].rstrip("，,；; ") + "。"

    return {
        "ok": True,
        "source_type": "plain_text",
        "input_kind": "text",
        "summary": summary,
        "keywords": top_keywords(text),
    }


def summarize_chat_log(text: str, max_sentences: int) -> dict:
    chat_lines = detect_chat_lines(text)
    if not chat_lines:
        return summarize_plain_text(text, max_sentences)

    speakers = []
    messages = []
    for speaker, message in chat_lines:
        speakers.append(speaker)
        messages.append(message)

    speaker_counts = Counter(speakers)
    merged_text = " ".join(messages)
    sentence_candidates = split_sentences(merged_text)
    frequencies = Counter(tokenize(merged_text))
    ranked = sorted(
        enumerate(sentence_candidates),
        key=lambda item: (sentence_score(item[1], frequencies), -item[0]),
        reverse=True,
    )
    chosen_indexes = sorted(index for index, _ in ranked[:max_sentences])
    chosen = [sentence_candidates[index] for index in chosen_indexes]
    core = " ".join(chosen) if chosen else normalize_space(merged_text[:180])

    speaker_text = "、".join(name for name, _ in speaker_counts.most_common(3))
    summary = (
        f"这段聊天记录主要围绕以下内容展开，参与者包括{speaker_text}：{normalize_space(core)}"
        if speaker_text
        else f"这段聊天记录主要围绕以下内容展开：{normalize_space(core)}"
    )
    if len(summary) > 240:
        summary = summary[:240].rstrip("，,；; ") + "。"

    return {
        "ok": True,
        "source_type": "plain_text",
        "input_kind": "chat_log",
        "summary": summary,
        "speakers": [name for name, _ in speaker_counts.most_common()],
        "keywords": top_keywords(merged_text),
    }


def build_text_title(result: dict) -> str:
    if result.get("input_kind") == "chat_log":
        speakers = result.get("speakers") or []
        if speakers:
            return f"{'、'.join(speakers[:2])}聊天总结"
        return "聊天记录总结"
    keywords = result.get("keywords") or []
    if keywords:
        return f"{'-'.join(keywords[:2])}文本总结"
    return "文本总结"


def render_text_document(result: dict, original_text: str) -> str:
    title = build_text_title(result)
    summary = result.get("summary", "")
    source_label = "钉钉聊天" if result.get("input_kind") == "chat_log" else "文本输入"
    return (
        f"# {title}\n\n"
        f"> 来源：{source_label}\n\n"
        f"## 总结\n{summary}\n\n"
        f"## 原文\n```text\n{original_text.strip()}\n```"
    )


def main() -> int:
    args = parse_args()
    text = load_text(args)

    if not normalize_space(text):
        print(json.dumps({"ok": False, "error": "usage: text_to_summary.py <text> | --text-file <path>"}, ensure_ascii=False))
        return 1

    if is_chat_log(text):
        result = summarize_chat_log(text, args.max_sentences)
    else:
        result = summarize_plain_text(text, args.max_sentences)

    if result.get("ok"):
        result.update(
            build_document_result(
                markdown=render_text_document(result, text),
                title=build_text_title(result),
                source_type="plain_text",
                input_kind=result.get("input_kind"),
                ingest=args.ingest,
                explicit_app_key=args.app_key,
                sender_id=args.sender_id,
                account_id=args.account_id,
                context_json=args.context_json,
            )
        )

    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
