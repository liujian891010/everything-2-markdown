# 文件处理流程

## 目标

把用户上传的本地文件直接整理成可入库的 Markdown 文档。

## 触发时机

- 用户上传本地文件后，如果 3 秒内没有追加新的操作指令，直接进入文件处理分支。
- 文件分支不再像 URL/视频那样先给摘要再等“是否继续整理”，而是直接调用解析 API。

## 处理入口

1. `scripts/detect_input.py --type file`
2. `scripts/file_to_markdown.py`

## 解析方式

- 检测到本地文件后，调用：

```bash
curl -sS --compressed -X POST \
  "https://{域名}/open-api/file-processing-service/v1/convert/upload-sync" \
  -H 'access-token: {accessToken}' \
  -F "file=@/path/to/local/document.pdf"
```

- `access-token` 优先取显式参数，其次复用 `cms-auth-skills` 自动解析。
- API 成功返回后，优先读取返回中的 `markdown`、`summary`、`keyPoints` 等字段。
- 如果接口没有直接返回 Markdown，则从 `text/content/pages/sections` 等字段回退拼装正文。

## 输出规则

- 统一输出 Markdown 文档，包含：
  - 标题
  - 文件元信息
  - 摘要
  - 关键点
  - 正文整理
- 文档生成完成后，直接进入“是否入库”确认阶段。

## 注意

- 文件不存在时直接报错，不要伪造正文。
- API 返回失败时，要保留失败原因。
- Office/PDF/图片的深度解析统一走文件解析 API，不再只停留在脚手架状态。
