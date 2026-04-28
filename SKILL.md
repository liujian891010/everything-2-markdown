---
name: everything-2-markdown
description: 当用户发来 YouTube 链接、普通 URL、抖音 URL、头条 URL、上传本地文件，或直接粘贴一段文本/聊天记录，并要求提取内容、整理结构、转换为 Markdown 或总结成简短文字时触发。先识别输入类型，再按来源进入独立处理流程。
---

# Everything 2 Markdown

## 触发判断

```text
收到用户输入
 ├─ YouTube URL      -> scripts/detect_input.py -> scripts/youtube_to_markdown.py
 ├─ 抖音 URL          -> scripts/detect_input.py -> scripts/douyin_to_markdown.py
 ├─ 头条 URL          -> scripts/detect_input.py -> scripts/toutiao_to_markdown.py
 ├─ 普通 URL          -> scripts/detect_input.py -> scripts/url_to_markdown.py
 ├─ 上传文件          -> scripts/detect_input.py -> scripts/file_to_markdown.py
 └─ 纯文本/聊天记录     -> scripts/detect_input.py -> scripts/text_to_summary.py
```

## 工作流

1. 先运行 `scripts/detect_input.py` 识别来源类型。
2. 根据来源进入对应的独立脚本，不要把所有来源混成一套逻辑。
3. 每个来源先做最小可用提取，再做 Markdown 规范化。
4. 输出前统一清理噪音内容：导航、分享文案、按钮文字、重复空行、无意义标签。
5. 如果来源内容抓取失败，返回失败原因和建议降级路径，不要伪造正文。
6. 生成文档时不要落盘到本地。
7. 文档统一命名为 `YYYY-MM-DD-001-标题.md` 这种格式，序号按当天自动递增。
8. 文档生成后直接调用 `cms-docdb` 入库，不再等待用户二次确认。
9. 入库参数固定为：`content=文档内容`、`fileName=文件名`、`fileSuffix=md`，`folderName` 按来源自动识别。

## 来源处理规则

### YouTube URL

- 不走通用网页抓取。
- 直接调用 `https://sg-al-cwork-web.mediportal.com.cn/video2markdown/parse`。
- 该接口需要 token，且是异步任务；必须等待成功结果。
- 成功后读取返回中的 `key_points` 和 `source_text`。
- 先根据 `key_points` 生成简单简介，并询问用户是否需要继续整理。
- 只有用户确认后，才用 `source_text` 结合 `references/report-template.md` 生成正式 Markdown 文档。
- 详细规则见 `references/youtube-workflow.md`。

### 普通 URL

- 不走单一抓取器。
- 按 `Tavily Extract API -> Jina.ai Reader -> LLM-Reader -> 裸 requests` 的顺序逐步降级。
- 只要任一层成功获取正文，就先生成简短摘要给用户。
- 如果最终仍未成功抓取内容，要明确提示用户抓取失败。
- 只有用户确认后，才把正文结合 `references/report-template.md` 生成正式 Markdown 文档。
- 详细规则见 `references/url-workflow.md`。

### 抖音 URL

- 不走通用网页抓取。
- 直接调用 `https://hk-al-xg-node.mediportal.com.cn/api/open/audio/export-with-asr`。
- 使用固定 `Bearer token` 鉴权。
- 返回中的 `asr_text` 视为正文来源。
- 先根据 `asr_text` 生成简单简介，并询问用户是否需要继续形成报告。
- 只有用户确认后，才用 `asr_text` 结合 `references/report-template.md` 生成正式 Markdown 文档。
- 详细规则见 `references/douyin-workflow.md`。

### 头条 URL

- 不走单一抓取器。
- 按 `Tavily Extract API -> Jina.ai Reader -> LLM-Reader -> 裸 requests` 的顺序逐步降级。
- 只要任一层成功获取正文，就先生成简短摘要给用户。
- 如果最终仍未成功抓取内容，要明确提示用户抓取失败。
- 只有用户确认后，才把正文结合 `references/report-template.md` 生成正式 Markdown 文档。
- 详细规则见 `references/toutiao-workflow.md`。

### 用户上传文件

- 先按扩展名和 MIME 粗分：文本、Markdown、HTML、JSON、CSV、日志、Office/PDF、图片。
- 能直接解析的先直接解析；不能直接解析的保留接口，后续接专门工具。
- 详细规则见 `references/file-workflow.md`。

### 文本 / 聊天记录

- 不走报告模板。
- 普通文本直接压缩成一段摘要。
- 聊天记录优先提取参与者、讨论重点和结论，合成一段总结。
- 总结结果也不落盘到本地；如需入库，包装成 Markdown 文档后再上传。
- 详细规则见 `references/text-workflow.md`。

## 脚本

| 脚本 | 用途 |
|------|------|
| `scripts/detect_input.py` | 识别输入是 YouTube / URL / 抖音 / 头条 / 文件 / 文本 |
| `scripts/youtube_to_markdown.py` | YouTube 专用入口 |
| `scripts/url_to_markdown.py` | 通用 URL 专用入口 |
| `scripts/douyin_to_markdown.py` | 抖音专用入口 |
| `scripts/toutiao_to_markdown.py` | 头条专用入口 |
| `scripts/file_to_markdown.py` | 上传文件专用入口 |
| `scripts/text_to_summary.py` | 文本/聊天记录总结入口 |

## 参考

| 文件 | 内容 |
|------|------|
| `references/decision-rules.md` | 来源识别与路由规则 |
| `references/youtube-workflow.md` | YouTube 处理流程 |
| `references/url-workflow.md` | 普通 URL 处理流程 |
| `references/douyin-workflow.md` | 抖音处理流程 |
| `references/toutiao-workflow.md` | 头条处理流程 |
| `references/file-workflow.md` | 文件处理流程 |
| `references/text-workflow.md` | 文本/聊天记录总结流程 |

## 边界

本 Skill 负责：识别来源、按来源分流、提取结构、输出 Markdown 或摘要、生成统一命名的文档，并直接调用 `cms-docdb` 入库。

本 Skill 暂不负责：真正的视频下载、浏览器自动化、OCR、Office/PDF 深度解析、云端同步。
