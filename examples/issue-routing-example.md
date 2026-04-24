# 示例：检测到用户是在反馈 bug 并要求提 issue

用户输入：

```text
这个头条分享链接识别错了，明明是头条却被当成普通文本。帮我提个 issue 到仓库。
```

预期路由：

- `scripts/detect_input.py`
- `scripts/report_github_issue.py`

预期行为：

1. 优先识别为 `issue_report`，而不是 `plain_text`。
2. 如果文本里能推断来源类型，补充 `source_type_hint`。
3. 如果文本里还带有 URL，补充 `related_url / related_kind / related_host`。
