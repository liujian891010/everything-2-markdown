# 示例：YouTube

用户输入：

```text
把这个 YouTube 视频转成 Markdown：https://www.youtube.com/watch?v=dQw4w9WgXcQ
```

预期路由：

- `scripts/detect_input.py`
- `scripts/youtube_to_markdown.py`

预期行为：

1. 先调用内部 `video2markdown/parse` 接口并等待成功。
2. 读取返回的 `key_points`，生成一个简单简介。
3. 询问用户是否需要继续整理。
4. 只有在用户确认后，才用 `source_text` 和 `references/report-template.md` 生成正式 Markdown。
