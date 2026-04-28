#!/usr/bin/env python3
"""Optional headless browser fallback for dynamic web pages."""
from __future__ import annotations

import re


DEFAULT_SELECTORS = (
    "article",
    "main",
    "[role='main']",
    ".article",
    ".article-content",
    ".content",
    ".main",
    ".post",
    ".entry-content",
)


def normalize_space(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def normalize_block_text(text: str | None) -> str:
    source = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    paragraphs: list[str] = []
    bucket: list[str] = []
    for raw_line in source.splitlines():
        line = normalize_space(raw_line)
        if not line:
            if bucket:
                paragraphs.append(" ".join(bucket))
                bucket = []
            continue
        bucket.append(line)
    if bucket:
        paragraphs.append(" ".join(bucket))
    return "\n\n".join(paragraphs)


def is_good_content(text: str | None, min_length: int = 120) -> bool:
    normalized = normalize_space(text)
    if len(normalized) < min_length:
        return False
    lower = normalized.lower()
    noisy_markers = ("captcha", "verify you are human", "access denied", "访问过于频繁")
    return not any(marker in lower for marker in noisy_markers)


def _extract_locator_text(page, selector: str, timeout_ms: int) -> str:
    try:
        locator = page.locator(selector)
        if locator.count() < 1:
            return ""
        return normalize_block_text(locator.first.inner_text(timeout=timeout_ms))
    except Exception:
        return ""


def fetch_via_headless_browser(
    url: str,
    *,
    min_length: int = 120,
    timeout_ms: int = 15000,
    selectors: tuple[str, ...] = DEFAULT_SELECTORS,
) -> dict | None:
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return None

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(
                user_agent=(
                    "Mozilla/5.0 (X11; Linux x86_64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/123.0.0.0 Safari/537.36"
                ),
                locale="zh-CN",
            )
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                page.wait_for_timeout(1200)
                try:
                    page.wait_for_load_state("networkidle", timeout=min(timeout_ms, 5000))
                except Exception:
                    pass

                title = normalize_space(page.title())
                content = ""
                for selector in selectors:
                    content = _extract_locator_text(page, selector, min(timeout_ms, 2500))
                    if is_good_content(content, min_length=min_length):
                        break

                if not is_good_content(content, min_length=min_length):
                    content = normalize_block_text(
                        page.locator("body").inner_text(timeout=min(timeout_ms, 4000))
                    )

                if not title and content:
                    first_line = next(
                        (line.strip() for line in content.splitlines() if line.strip()),
                        "",
                    )
                    title = first_line[:80]

                if not is_good_content(content, min_length=min_length):
                    return None

                return {
                    "extractor_used": "headless_browser",
                    "title": title,
                    "content": content,
                }
            finally:
                browser.close()
    except Exception:
        return None
