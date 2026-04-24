# 示例：上传本地文件

用户输入：

```text
把我上传的 `meeting-notes.docx` 转成 Markdown
```

触发行为：

1. 用户上传文件后 3 秒内没有追加新操作。
2. 直接走 `scripts/detect_input.py --type file`。
3. `detect_input.py` 会先返回文件策略，例如：
   - `file_processing_strategy = local_text`
   - `file_processing_strategy = local_office_then_api`
   - `file_processing_strategy = api_direct`
4. 还会补充 `file_processing_reason`，说明为什么命中该策略。
5. 再进入 `scripts/file_to_markdown.py`。

预期行为：

1. 先根据扩展名判断处理策略。
2. 如果是文本类文件，优先本地解析。
3. 如果是 `docx / pptx / xlsx`，先做本地轻解析。
4. 如果本地轻解析失败或内容过少，再自动调用 `file-processing-service` 的 `convert/upload-sync` 接口。
5. 如果是 `pdf / 图片 / 旧 Office / 未知格式`，直接调用 API。
6. 生成正式 Markdown 后，只询问一次“是否入库？”。
