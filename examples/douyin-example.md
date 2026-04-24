# 示例：抖音 URL

用户输入：

```text
把这个抖音链接整理成 Markdown：https://v.douyin.com/abcdefg/
```

预期路由：

- `scripts/detect_input.py`
- `scripts/douyin_to_markdown.py`

预期行为：

1. 调用抖音 ASR 接口，拿到 `asr_text`。
2. 基于 `asr_text` 生成一个简单简介。
3. 先展示简介并询问用户是否需要形成报告。
4. 只有在用户确认后，才用 `asr_text` 和 `references/report-template.md` 生成正式 Markdown。
