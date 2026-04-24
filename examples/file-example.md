# 示例：上传本地文件

用户输入：

```text
把我上传的 `meeting-notes.pdf` 转成 Markdown
```

触发行为：

1. 用户上传文件后 3 秒内没有追加新操作。
2. 直接走 `scripts/detect_input.py --type file`。
3. 再进入 `scripts/file_to_markdown.py`。

预期行为：

1. 检测到本地文件路径。
2. 调用 `file-processing-service` 的 `convert/upload-sync` 接口上传文件。
3. 从接口返回中提取 `markdown / text / summary / keyPoints`。
4. 直接生成正式 Markdown 文档。
5. 文档生成后只询问一次“是否入库？”。
