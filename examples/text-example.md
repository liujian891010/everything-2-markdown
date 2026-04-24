# 示例：文本 / 聊天记录

用户输入：

```text
张三：今天先把 URL 工作流补齐。
李四：可以，普通 URL 和头条先统一降级链。
张三：文件工作流先不动，下一步补文本总结。
```

预期路由：

- `scripts/detect_input.py`
- `scripts/text_to_summary.py`

预期行为：

1. 判断输入为聊天记录或普通文本
2. 直接输出一段简短总结
3. 不进入 Markdown 报告模板流程
