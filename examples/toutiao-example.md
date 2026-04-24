# 示例：头条 URL

用户输入：

```text
把这个头条文章转成 Markdown：https://www.toutiao.com/article/1234567890/
```

预期路由：

- `scripts/detect_input.py`
- `scripts/toutiao_to_markdown.py`

预期行为：

1. 先按 `Tavily Extract -> Jina Reader -> LLM-Reader -> 裸 requests` 的顺序抓取正文。
2. 一旦成功拿到正文，先生成简短摘要。
3. 先展示摘要并询问用户是否需要形成报告。
4. 只有在用户确认后，才用正文和 `references/report-template.md` 生成正式 Markdown。
