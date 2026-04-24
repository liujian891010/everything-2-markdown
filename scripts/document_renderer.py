#!/usr/bin/env python3
"""Shared markdown rendering with lightweight template selection."""
from __future__ import annotations

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
    cleaned = re.sub(r"^\s*[-*+]\s+", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"^\s*\d+\.\s+", "", cleaned, flags=re.MULTILINE)
    return normalize_space(cleaned)


def split_paragraphs(text: str) -> list[str]:
    source = (text or "").replace("\r\n", "\n").strip()
    if not source:
        return []

    blocks = []
    bucket = []
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


def bullets_from_key_points(key_points: list[str]) -> str:
    if not key_points:
        return "- 暂无明确关键点"
    return "\n".join(f"- {point}" for point in key_points)


def fenced_source_text(source_text: str) -> str:
    if not (source_text or "").strip():
        return "```text\n暂无原始文本\n```"
    return f"```text\n{source_text.strip()}\n```"


def organize_source_text(source_text: str) -> str:
    paragraphs = split_paragraphs(source_text)
    if paragraphs:
        return "\n\n".join(paragraphs)
    normalized = normalize_space(source_text)
    return normalized or "暂无可用正文。"


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


def _steps_section(paragraphs: list[str]) -> str:
    if not paragraphs:
        return "### 2.1 过程整理\n\n暂无可用步骤。"

    rendered = []
    for index, paragraph in enumerate(paragraphs[:6], start=1):
        rendered.append(f"### 2.{index} 步骤 {index}\n\n{paragraph}")
    return "\n\n".join(rendered)


def _logic_section(paragraphs: list[str]) -> str:
    if not paragraphs:
        return "### 2.1 逻辑分析\n- **位置**: 整体内容\n- **逻辑**: 暂无可用正文\n- **效果**: 待补充"

    rendered = []
    for index, paragraph in enumerate(paragraphs[:4], start=1):
        rendered.append(
            f"### 2.{index} 逻辑 {index}\n"
            f"- **位置**: 内容片段 {index}\n"
            f"- **逻辑**: {paragraph}\n"
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
    template_kind = choose_template_kind(
        title=title,
        summary=summary,
        key_points=key_points,
        source_text=source_text,
        source_platform=source_platform,
    )
    if template_kind == "practical_record":
        markdown = render_practical_record(
            title=title,
            source_platform=source_platform,
            source_url=source_url,
            summary=summary,
            key_points=key_points,
            source_text=source_text,
        )
    elif template_kind == "research_survey":
        markdown = render_research_survey(
            title=title,
            source_platform=source_platform,
            source_url=source_url,
            summary=summary,
            key_points=key_points,
            source_text=source_text,
        )
    elif template_kind == "tech_analysis":
        markdown = render_tech_analysis(
            title=title,
            source_platform=source_platform,
            source_url=source_url,
            summary=summary,
            key_points=key_points,
            source_text=source_text,
        )
    else:
        template_kind = "report"
        markdown = render_report(
            title=title,
            source_platform=source_platform,
            source_url=source_url,
            summary=summary,
            key_points=key_points,
            source_text=source_text,
        )

    return {
        "template_name": template_kind,
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
    return (
        f"# {title}\n\n"
        f"> 来源：{source_platform}\n"
        f"> 链接：{source_url}\n"
        f"> 整理日期：{date.today().isoformat()}\n\n"
        "---\n\n"
        f"## 简介\n{summary}\n\n"
        f"## 关键要点\n{bullets_from_key_points(key_points)}\n\n"
        f"## 正文整理\n{organize_source_text(source_text)}\n\n"
        f"## 原始文本\n{fenced_source_text(source_text)}\n"
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
    paragraphs = split_paragraphs(source_text)
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
        f"{_steps_section(paragraphs)}\n\n"
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
    paragraphs = split_paragraphs(source_text)
    descriptor = key_points[0] if key_points else summary
    descriptor = descriptor[:60] if descriptor else "内容调研"
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
        f"{organize_source_text(source_text[:1200])}\n\n"
        f"{_feature_table(key_points)}\n\n"
        "---\n\n"
        "## 三、技术实现逻辑 (Mechanism)\n\n"
        f"{organize_source_text(source_text)}\n\n"
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
    paragraphs = split_paragraphs(source_text)
    pain_points = key_points[:2] if key_points else [summary]
    pain_lines = "\n".join(f"{index}. {point}" for index, point in enumerate(pain_points, start=1))
    if not pain_lines:
        pain_lines = "1. 暂无明确痛点"

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
        f"{_logic_section(paragraphs)}\n\n"
        "---\n\n"
        "## 三、关键结论与效果观察\n\n"
        f"{_observation_table(key_points)}\n\n"
        "---\n\n"
        "## 四、对当前项目的启示 (Actionable Insights)\n\n"
        f"{_insight_table(key_points)}\n\n"
        "---\n\n"
        "## 原始文本\n"
        f"{fenced_source_text(source_text)}\n"
    )
