#!/usr/bin/env python3
"""Shared markdown rendering with lightweight template selection."""
from __future__ import annotations

import math
import re
from datetime import date
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
REFERENCE_DIR = SKILL_DIR / "references"
TEMPLATE_FILES = {
    "report": REFERENCE_DIR / "report-template.md",
    "practical_record": REFERENCE_DIR / "practical_record.md",
    "research_survey": REFERENCE_DIR / "research_survey.md",
    "tech_analysis": REFERENCE_DIR / "tech_analysis.md",
}

PRACTICAL_KEYWORDS = (
    "实战", "实践", "教程", "指南", "步骤", "搭建", "部署", "配置", "手把手",
    "经验", "操作", "workflow", "guide", "tutorial", "how to", "runbook",
    "implementation", "best practice",
)
RESEARCH_KEYWORDS = (
    "调研", "survey", "盘点", "汇总", "合集", "综述", "对比", "评测", "评估",
    "观察", "选型", "comparison", "landscape", "overview", "benchmark",
    "research", "review", "roundup",
)
TECH_KEYWORDS = (
    "技术", "原理", "架构", "源码", "机制", "分析", "实现", "深度", "底层",
    "pipeline", "framework", "engine", "deep dive", "system", "logic",
    "llm", "agent", "推理", "模型",
)

PLACEHOLDER_BODY = "暂无可用正文。"
PLACEHOLDER_SUMMARY = "已完成内容整理，但暂未提炼出稳定摘要。"
PLACEHOLDER_KEY_POINT = "暂无明确关键要点"
ORDERED_PREFIX_RE = re.compile(
    r"^(?:\d{1,2}[.)、]|[一二三四五六七八九十]+[、.]|第(?:\d{1,2}|[一二三四五六七八九十]+)(?:点|步|部分|阶段|条|项))\s*"
)
INLINE_ENUMERATION_SPLIT_RE = re.compile(
    r"(?=(?:\d{1,2}[.)、]|[一二三四五六七八九十]+[、.]|第(?:\d{1,2}|[一二三四五六七八九十]+)(?:点|步|部分|阶段|条|项))\s*)"
)
LEADING_LIST_RE = re.compile(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)")


def normalize_newlines(text: str | None) -> str:
    return (text or "").replace("\r\n", "\n").replace("\r", "\n")


def normalize_space(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def strip_markdown(text: str) -> str:
    cleaned = re.sub(r"```[\s\S]*?```", " ", text or "")
    cleaned = re.sub(r"`([^`]+)`", r"\1", cleaned)
    cleaned = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", cleaned)
    cleaned = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", cleaned)
    cleaned = re.sub(r"^\s{0,3}#+\s*", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"^\s*>+\s*", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"^\s*[-*+]\s+", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"^\s*\d+\.\s+", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"^\s*\d+\)\s+", "", cleaned, flags=re.MULTILINE)
    return normalize_space(cleaned)


def split_paragraphs(text: str) -> list[str]:
    source = normalize_newlines(text).strip()
    if not source:
        return []

    blocks: list[str] = []
    bucket: list[str] = []
    for raw_line in source.splitlines():
        line = raw_line.strip()
        if not line:
            if bucket:
                blocks.append(" ".join(bucket))
                bucket = []
            continue
        bucket.append(line)
    if bucket:
        blocks.append(" ".join(bucket))
    return blocks


def split_blocks_preserving_fences(text: str) -> list[str]:
    source = normalize_newlines(text).strip()
    if not source:
        return []

    blocks: list[str] = []
    bucket: list[str] = []
    in_fence = False
    for raw_line in source.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if stripped.startswith("```"):
            bucket.append(line)
            in_fence = not in_fence
            continue
        if not in_fence and not stripped:
            if bucket:
                blocks.append("\n".join(bucket).strip())
                bucket = []
            continue
        bucket.append(line)
    if bucket:
        blocks.append("\n".join(bucket).strip())
    return blocks


def bullets_from_key_points(key_points: list[str]) -> str:
    if not key_points:
        return f"- {PLACEHOLDER_KEY_POINT}"
    return "\n".join(f"- {point}" for point in key_points)


def fenced_source_text(source_text: str) -> str:
    if not (source_text or "").strip():
        return "```text\n暂无原始文本\n```"
    return f"```text\n{source_text.strip()}\n```"


def has_source_text(source_text: str) -> bool:
    return bool(normalize_space(source_text))


def render_source_text_section(source_text: str) -> str:
    if not has_source_text(source_text):
        return ""
    return f"## 原始文本\n{fenced_source_text(source_text)}\n"


def _trim_trailing_punctuation(text: str) -> str:
    return text.rstrip("。；;，,、!！?？:： ")


def compress_key_point(text: str, *, max_chars: int = 72) -> str:
    normalized = normalize_space(strip_markdown(text))
    normalized = LEADING_LIST_RE.sub("", normalized)
    normalized = ORDERED_PREFIX_RE.sub("", normalized)
    normalized = _trim_trailing_punctuation(normalized)
    if not normalized:
        return ""
    if len(normalized) <= max_chars:
        return normalized

    sentences = split_sentences(normalized)
    if len(sentences) > 1:
        candidate = _trim_trailing_punctuation(" ".join(sentences[:2]))
        if len(candidate) <= max_chars:
            return candidate
        normalized = candidate

    clauses = [chunk.strip() for chunk in re.split(r"[，,；;：:]", normalized) if chunk.strip()]
    if len(clauses) > 1:
        candidate = _trim_trailing_punctuation("，".join(clauses[:2]))
        if len(candidate) <= max_chars:
            return candidate
        normalized = candidate

    if len(normalized) <= max_chars:
        return normalized
    return normalized[: max_chars - 3].rstrip() + "..."


def polish_key_points(
    key_points: list[str] | None,
    *,
    fallback_text: str = "",
    max_items: int = 4,
) -> list[str]:
    candidates = list(key_points or [])
    if not candidates and fallback_text:
        candidates = split_sentences(strip_markdown(fallback_text))[: max(max_items * 2, 6)]

    polished: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        compact = compress_key_point(candidate)
        if not compact:
            continue
        signature = re.sub(r"[\W_]+", "", compact).lower()
        if not signature or signature in seen:
            continue
        seen.add(signature)
        polished.append(compact)
        if len(polished) >= max_items:
            break
    return polished


def build_summary_from_key_points(key_points: list[str], *, prefix: str = "核心内容") -> str:
    selected = [_trim_trailing_punctuation(item) for item in key_points if item.strip()][:3]
    if not selected:
        return PLACEHOLDER_SUMMARY
    if len(selected) == 1:
        return f"{prefix}围绕：{selected[0]}。"
    if len(selected) == 2:
        return f"{prefix}主要包括：{selected[0]}；{selected[1]}。"
    return f"{prefix}主要围绕以下几点展开：{selected[0]}；{selected[1]}；{selected[2]}。"


def polish_summary(
    summary: str | None,
    key_points: list[str] | None = None,
    *,
    fallback_text: str = "",
    prefix: str = "核心内容",
    max_chars: int = 120,
) -> str:
    polished_points = polish_key_points(key_points or [], fallback_text=fallback_text)
    normalized = normalize_space(strip_markdown(summary or ""))
    normalized = re.sub(r"\s*([。！？!?；;])\s*", r"\1 ", normalized).strip()

    if not normalized:
        if polished_points:
            return build_summary_from_key_points(polished_points, prefix=prefix)
        fallback_sentences = split_sentences(strip_markdown(fallback_text))
        if fallback_sentences:
            normalized = " ".join(fallback_sentences[:2])
        else:
            return PLACEHOLDER_SUMMARY

    sentences = split_sentences(normalized)
    candidate = " ".join(sentences[:2]) if sentences else normalized
    candidate = candidate.strip()
    if len(candidate) > max_chars and polished_points:
        generated = build_summary_from_key_points(polished_points, prefix=prefix)
        if len(generated) <= len(candidate):
            candidate = generated
    if len(candidate) > max_chars:
        candidate = candidate[: max_chars - 3].rstrip() + "..."
    return candidate or PLACEHOLDER_SUMMARY


def has_markdown_structure(text: str) -> bool:
    stripped = normalize_newlines(text).strip()
    if not stripped:
        return False

    checks = (
        re.search(r"^\s{0,3}#{1,6}\s+", stripped, flags=re.MULTILINE),
        re.search(r"^\s*[-*+]\s+", stripped, flags=re.MULTILINE),
        re.search(r"^\s*\d+[.)]\s+", stripped, flags=re.MULTILINE),
        re.search(r"^\s*>+\s+", stripped, flags=re.MULTILINE),
        re.search(r"^\s*\|.+\|\s*$", stripped, flags=re.MULTILINE),
        "```" in stripped,
    )
    return any(checks)


def block_is_code(block: str) -> bool:
    stripped = block.strip()
    return stripped.startswith("```") and stripped.endswith("```")


def block_is_table(block: str) -> bool:
    lines = [line.strip() for line in block.splitlines() if line.strip()]
    return len(lines) >= 2 and sum(1 for line in lines if "|" in line) >= 2


def block_is_list(block: str) -> bool:
    lines = [line.strip() for line in block.splitlines() if line.strip()]
    if not lines:
        return False
    return all(
        re.match(r"^(?:[-*+]\s+|\d+[.)]\s+)", line)
        for line in lines
    )


def block_is_quote(block: str) -> bool:
    lines = [line.strip() for line in block.splitlines() if line.strip()]
    return bool(lines) and all(line.startswith(">") for line in lines)


def normalize_structured_block(block: str) -> str:
    return "\n".join(line.rstrip() for line in normalize_newlines(block).splitlines()).strip()


def split_sentences(text: str) -> list[str]:
    normalized = normalize_space(text)
    if not normalized:
        return []
    prepared = re.sub(r"([。！？!?；;]+)", r"\1\n", normalized)
    prepared = re.sub(r"\.(\s+)(?=[A-Z0-9\u4e00-\u9fff])", ".\n", prepared)
    sentences = [part.strip() for part in prepared.splitlines() if part.strip()]
    return sentences or [normalized]


def group_sentences(
    sentences: list[str],
    *,
    max_chars: int = 180,
    max_sentences: int = 3,
) -> list[str]:
    paragraphs: list[str] = []
    bucket: list[str] = []
    bucket_chars = 0
    for sentence in sentences:
        compact = normalize_space(sentence)
        if not compact:
            continue
        projected = bucket_chars + len(compact) + (1 if bucket else 0)
        if bucket and (len(bucket) >= max_sentences or projected > max_chars):
            paragraphs.append(" ".join(bucket))
            bucket = [compact]
            bucket_chars = len(compact)
        else:
            bucket.append(compact)
            bucket_chars = projected
    if bucket:
        paragraphs.append(" ".join(bucket))
    return paragraphs


def extract_inline_list_items(text: str) -> list[str]:
    normalized = normalize_space(text)
    if not normalized:
        return []
    if len(INLINE_ENUMERATION_SPLIT_RE.findall(normalized)) < 3:
        return []

    parts = [part.strip() for part in INLINE_ENUMERATION_SPLIT_RE.split(normalized) if part.strip()]
    items: list[str] = []
    for part in parts:
        if not ORDERED_PREFIX_RE.match(part):
            continue
        cleaned = ORDERED_PREFIX_RE.sub("", part).strip(" ：:;；，,。")
        if cleaned:
            items.append(cleaned)
    return items if len(items) >= 3 else []


def format_plain_block(block: str) -> str:
    normalized = normalize_space(block)
    if not normalized:
        return ""

    inline_items = extract_inline_list_items(normalized)
    if inline_items:
        return "\n".join(f"- {item}" for item in inline_items)

    sentences = split_sentences(normalized)
    if len(sentences) <= 2 and len(normalized) <= 180:
        return normalized

    paragraphs = group_sentences(sentences)
    return "\n\n".join(paragraphs) if paragraphs else normalized


def sectionize_paragraphs(paragraphs: list[str]) -> str:
    cleaned = [paragraph.strip() for paragraph in paragraphs if paragraph.strip()]
    if len(cleaned) < 4:
        return "\n\n".join(cleaned) if cleaned else PLACEHOLDER_BODY

    if len(cleaned) >= 7:
        titles = ["### 核心内容", "### 关键细节", "### 补充说明"]
    else:
        titles = ["### 核心内容", "### 关键细节"]

    chunk_size = max(1, math.ceil(len(cleaned) / len(titles)))
    sections: list[str] = []
    start = 0
    for title in titles:
        chunk = cleaned[start:start + chunk_size]
        if not chunk:
            continue
        sections.append(f"{title}\n\n" + "\n\n".join(chunk))
        start += chunk_size
    return "\n\n".join(sections)


def beautify_plain_text(text: str) -> str:
    paragraphs = split_paragraphs(text)
    if not paragraphs:
        normalized = normalize_space(text)
        return normalized or PLACEHOLDER_BODY

    rendered_blocks = [format_plain_block(paragraph) for paragraph in paragraphs if paragraph.strip()]
    joined = "\n\n".join(block for block in rendered_blocks if block.strip()).strip()
    if not joined:
        return PLACEHOLDER_BODY

    flattened = split_paragraphs(joined)
    if len(paragraphs) == 1 and len(flattened) >= 4:
        return sectionize_paragraphs(flattened)
    return joined


def beautify_markdown_text(text: str) -> str:
    blocks = split_blocks_preserving_fences(text)
    if not blocks:
        return PLACEHOLDER_BODY

    rendered: list[str] = []
    plain_blocks = 0
    for block in blocks:
        if block_is_code(block) or block_is_table(block) or block_is_list(block) or block_is_quote(block):
            rendered.append(normalize_structured_block(block))
            continue
        if re.match(r"^\s{0,3}#{1,6}\s+", block.strip()):
            rendered.append(normalize_structured_block(block))
            continue
        plain_blocks += 1
        rendered.append(format_plain_block(block))

    compact = [item.strip() for item in rendered if item.strip()]
    if len(compact) == 1 and plain_blocks == 1:
        flattened = split_paragraphs(compact[0])
        if len(flattened) >= 4:
            return sectionize_paragraphs(flattened)
    return "\n\n".join(compact) if compact else PLACEHOLDER_BODY


def organize_source_text(source_text: str) -> str:
    source = normalize_newlines(source_text).strip()
    if not source:
        return PLACEHOLDER_BODY
    if has_markdown_structure(source):
        return beautify_markdown_text(source)
    return beautify_plain_text(source)


def extract_content_units(source_text: str, *, max_units: int) -> list[str]:
    plain_text = strip_markdown(source_text)
    if not plain_text:
        return []

    paragraphs = split_paragraphs(organize_source_text(plain_text))
    if paragraphs:
        return paragraphs[:max_units]

    sentences = split_sentences(plain_text)
    return group_sentences(sentences, max_chars=140, max_sentences=2)[:max_units]


def _keyword_score(text: str, keywords: tuple[str, ...], *, title_text: str) -> int:
    score = 0
    for keyword in keywords:
        if keyword in title_text:
            score += 3
        if keyword in text:
            score += 1
    return score


def choose_template_kind(
    *,
    title: str,
    summary: str,
    key_points: list[str],
    source_text: str,
    source_platform: str,
) -> str:
    title_text = normalize_space(title).lower()
    full_text = " ".join(
        normalize_space(item) for item in [title, summary, *key_points, source_text[:2000]]
    ).lower()

    scores = {
        "practical_record": _keyword_score(full_text, PRACTICAL_KEYWORDS, title_text=title_text),
        "research_survey": _keyword_score(full_text, RESEARCH_KEYWORDS, title_text=title_text),
        "tech_analysis": _keyword_score(full_text, TECH_KEYWORDS, title_text=title_text),
    }

    if source_platform in {"YouTube", "抖音"} and scores["practical_record"] > 0:
        scores["practical_record"] += 1

    best_kind = max(scores, key=scores.get)
    if scores[best_kind] <= 0:
        return "report"
    if not TEMPLATE_FILES.get(best_kind, Path()).exists():
        return "report"
    return best_kind


def _component_table(key_points: list[str]) -> str:
    rows = ["| 组件/主题 | 说明 |", "| :--- | :--- |"]
    for index, point in enumerate(key_points[:4], start=1):
        rows.append(f"| 要点 {index} | {point} |")
    if len(rows) == 2:
        rows.append("| 核心内容 | 暂无明确关键点 |")
    return "\n".join(rows)


def _feature_table(key_points: list[str]) -> str:
    rows = ["| 特性 | 关键点 | 备注 |", "| :--- | :--- | :--- |"]
    for index, point in enumerate(key_points[:4], start=1):
        rows.append(f"| 特性 {index} | {point} | 来源整理 |")
    if len(rows) == 2:
        rows.append("| 暂无明确特性 | 暂无明确关键点 | - |")
    return "\n".join(rows)


def _insight_table(key_points: list[str]) -> str:
    rows = ["| 关键发现 | 建议动作 | 优先级 |", "| :--- | :--- | :--- |"]
    for index, point in enumerate(key_points[:3], start=1):
        priority = "高" if index == 1 else "中"
        rows.append(f"| {point} | 继续补充验证与沉淀 | {priority} |")
    if len(rows) == 2:
        rows.append("| 暂无明确发现 | 继续补充上下文 | 中 |")
    return "\n".join(rows)


def _observation_table(key_points: list[str]) -> str:
    rows = ["| 维度 | 当前观察 | 对当前项目的启示 |", "| :--- | :--- | :--- |"]
    for index, point in enumerate(key_points[:3], start=1):
        rows.append(f"| 观察 {index} | {point} | 可继续纳入后续方案设计 |")
    if len(rows) == 2:
        rows.append("| 暂无明确观察 | 暂无明确内容 | 继续补充样本 |")
    return "\n".join(rows)


def _steps_section(source_text: str) -> str:
    units = extract_content_units(source_text, max_units=6)
    if not units:
        return "### 2.1 过程整理\n\n暂无可用步骤。"

    rendered = []
    for index, unit in enumerate(units, start=1):
        rendered.append(f"### 2.{index} 步骤 {index}\n\n{unit}")
    return "\n\n".join(rendered)


def _logic_section(source_text: str) -> str:
    units = extract_content_units(source_text, max_units=4)
    if not units:
        return "### 2.1 逻辑分析\n- **位置**: 整体内容\n- **逻辑**: 暂无可用正文\n- **效果**: 待补充"

    rendered = []
    for index, unit in enumerate(units, start=1):
        rendered.append(
            f"### 2.{index} 逻辑 {index}\n"
            f"- **位置**: 内容片段 {index}\n"
            f"- **逻辑**: {unit}\n"
            f"- **效果**: 可作为后续分析依据"
        )
    return "\n\n".join(rendered)


def _research_relation_table(source_platform: str) -> str:
    return (
        "| 当前项目 | 调研对象 | 差异/启示 |\n"
        "| :--- | :--- | :--- |\n"
        f"| everything-2-markdown | {source_platform} 内容样本 | 可借鉴结构化整理方式并补充落地规则 |"
    )


def render_document(
    *,
    title: str,
    source_platform: str,
    source_url: str,
    summary: str,
    key_points: list[str],
    source_text: str,
) -> dict:
    display_key_points = polish_key_points(key_points, fallback_text=source_text)
    display_summary = polish_summary(summary, display_key_points, fallback_text=source_text)
    template_kind = choose_template_kind(
        title=title,
        summary=display_summary,
        key_points=display_key_points,
        source_text=source_text,
        source_platform=source_platform,
    )
    if template_kind == "practical_record":
        markdown = render_practical_record(
            title=title,
            source_platform=source_platform,
            source_url=source_url,
            summary=display_summary,
            key_points=display_key_points,
            source_text=source_text,
        )
    elif template_kind == "research_survey":
        markdown = render_research_survey(
            title=title,
            source_platform=source_platform,
            source_url=source_url,
            summary=display_summary,
            key_points=display_key_points,
            source_text=source_text,
        )
    elif template_kind == "tech_analysis":
        markdown = render_tech_analysis(
            title=title,
            source_platform=source_platform,
            source_url=source_url,
            summary=display_summary,
            key_points=display_key_points,
            source_text=source_text,
        )
    else:
        template_kind = "report"
        markdown = render_report(
            title=title,
            source_platform=source_platform,
            source_url=source_url,
            summary=display_summary,
            key_points=display_key_points,
            source_text=source_text,
        )

    return {
        "template_name": template_kind,
        "summary": display_summary,
        "key_points": display_key_points,
        "markdown": markdown,
    }


def render_report(
    *,
    title: str,
    source_platform: str,
    source_url: str,
    summary: str,
    key_points: list[str],
    source_text: str,
) -> str:
    organized_body = organize_source_text(source_text)
    raw_section = render_source_text_section(source_text)
    return (
        f"# {title}\n\n"
        f"> 来源：{source_platform}\n"
        f"> 链接：{source_url}\n"
        f"> 整理日期：{date.today().isoformat()}\n\n"
        "---\n\n"
        f"## 简介\n{summary}\n\n"
        f"## 关键要点\n{bullets_from_key_points(key_points)}\n\n"
        f"## 正文整理\n{organized_body}\n\n"
        f"{raw_section}"
    )


def render_practical_record(
    *,
    title: str,
    source_platform: str,
    source_url: str,
    summary: str,
    key_points: list[str],
    source_text: str,
) -> str:
    return (
        f"# {title}\n\n"
        f"> 日期：{date.today().isoformat()}\n"
        f"> 执行者：everything-2-markdown\n"
        f"> 目标：{summary}\n"
        f"> 来源：{source_platform} | {source_url}\n\n"
        "---\n\n"
        "## 一、方案设计 (The Design)\n\n"
        "### 1.1 背景与目标\n"
        f"{summary}\n\n"
        "### 1.2 核心组件\n"
        f"{_component_table(key_points)}\n\n"
        "---\n\n"
        "## 二、实现步骤 (Implementation)\n\n"
        f"{_steps_section(source_text)}\n\n"
        "---\n\n"
        "## 三、关键发现与启发 (Philosophy & Lessons)\n\n"
        f"> **{summary}**\n\n"
        f"{bullets_from_key_points(key_points)}\n\n"
        "---\n\n"
        "## 四、后续优化方案 (Next Steps)\n\n"
        "- [ ] 继续补充关键细节与可复用步骤\n"
        "- [ ] 按需补充配图、命令或操作样例\n"
    )


def render_research_survey(
    *,
    title: str,
    source_platform: str,
    source_url: str,
    summary: str,
    key_points: list[str],
    source_text: str,
) -> str:
    descriptor = key_points[0] if key_points else summary
    descriptor = descriptor[:60] if descriptor else "内容调研"
    overview_units = extract_content_units(source_text, max_units=4)
    overview_body = "\n\n".join(overview_units) if overview_units else organize_source_text(source_text[:1200])
    mechanism_body = organize_source_text(source_text)
    return (
        f"# {title}：{descriptor}\n\n"
        f"> 来源：{source_url}\n"
        f"> 调研日期：{date.today().isoformat()}\n"
        "> 调研者：everything-2-markdown\n\n"
        "---\n\n"
        "## 一、项目 / 工具概览\n\n"
        "| 字段 | 内容 |\n"
        "| :--- | :--- |\n"
        f"| **定位** | {summary} |\n"
        f"| **核心指标** | {('；'.join(key_points[:3]) or '待补充')} |\n"
        f"| **一句话宗旨** | {descriptor} |\n\n"
        "---\n\n"
        "## 二、核心特性与能力\n\n"
        f"{overview_body}\n\n"
        f"{_feature_table(key_points)}\n\n"
        "---\n\n"
        "## 三、技术实现逻辑 (Mechanism)\n\n"
        f"{mechanism_body}\n\n"
        "---\n\n"
        "## 四、与当前项目的关系 (Relationship)\n\n"
        f"{_research_relation_table(source_platform)}\n\n"
        "---\n\n"
        "## 五、结论与下一步行动 (Next Actions)\n\n"
        "- [ ] 补充更多样本，完善调研结论\n"
        "- [ ] 将关键观察转为结构化规则或实现项\n"
        f"- [ ] 复核重点内容：{('；'.join(key_points[:2]) or '暂无明确重点')}\n"
    )


def render_tech_analysis(
    *,
    title: str,
    source_platform: str,
    source_url: str,
    summary: str,
    key_points: list[str],
    source_text: str,
) -> str:
    pain_points = key_points[:2] if key_points else [summary]
    pain_lines = "\n".join(f"{index}. {point}" for index, point in enumerate(pain_points, start=1))
    if not pain_lines:
        pain_lines = "1. 暂无明确痛点"
    raw_section = render_source_text_section(source_text)

    return (
        f"# {title} 深度解析\n\n"
        f"> 来源：{source_url}\n"
        "> 核心受众：技术分析 / 工程实现相关读者\n"
        f"> 调研日期：{date.today().isoformat()}\n"
        f"> 平台：{source_platform}\n\n"
        "---\n\n"
        "## 一、问题背景与痛点 (The Pain Points)\n\n"
        f"{pain_lines}\n\n"
        "---\n\n"
        "## 二、核心配置 / 逻辑分析 (Key Logic)\n\n"
        f"{_logic_section(source_text)}\n\n"
        "---\n\n"
        "## 三、关键结论与效果观察\n\n"
        f"{_observation_table(key_points)}\n\n"
        "---\n\n"
        "## 四、对当前项目的启示 (Actionable Insights)\n\n"
        f"{_insight_table(key_points)}\n\n"
        + ("---\n\n" + raw_section if raw_section else "")
    )
