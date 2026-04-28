# 文件处理流程

## 目标

把用户上传的本地文件整理成可入库的 Markdown 文档，同时优先利用本地可直接解析的能力，只有在必要时才调用远端解析 API。

## 触发时机

- 用户上传本地文件后，如果 3 秒内没有追加新的操作指令，直接进入文件处理分支。
- 文件分支生成正式 Markdown 后，直接上传到 `cms-docdb`。

## 处理入口

1. `scripts/detect_input.py --type file`
2. `scripts/file_to_markdown.py`

## 处理顺序

### 1. 本地直接解析

适用文件：

- `.txt`
- `.md`
- `.markdown`
- `.html`
- `.htm`
- `.json`
- `.csv`
- `.tsv`
- `.log`
- `.xml`
- `.yaml`
- `.yml`

特点：

- 不依赖 token
- 不依赖网络
- 速度快
- 优先走本地 Python 解析

### 2. 本地轻解析

适用文件：

- `.docx`
- `.pptx`
- `.xlsx`

特点：

- 先用本地 Python 做轻量提取
- 如果提取内容太少、结构不可用或解析失败，再降级到远端 API

### 3. API 深解析

默认直接走 API 的文件：

- `.pdf`
- `.doc`
- `.ppt`
- `.xls`
- 图片文件
- 未知格式文件

以及：

- 本地轻解析失败的 `docx / pptx / xlsx`
- 本地文本解析异常时的兜底情况

## API 调用

```bash
curl -sS --compressed -X POST \
  "https://{域名}/open-api/file-processing-service/v1/convert/upload-sync" \
  -H 'access-token: {accessToken}' \
  -F "file=@/path/to/local/document.pdf"
```

- 默认 `api base url` 为 `https://sg-al-cwork-web.mediportal.com.cn`
- `access-token` 优先取显式参数，其次复用 `cms-auth-skills` 自动解析

## 输出规则

- 统一输出 Markdown 文档，包含：
  - 标题
  - 文件元信息
  - 摘要
  - 关键点
  - 正文整理
- 结果中会补充：
  - `processing_mode`
  - `used_api_fallback`
  - `fallback_reason`（如果发生降级）

## 注意

- 文件不存在时直接报错，不要伪造正文。
- 文本类文件不要无脑先调 API。
- PDF、图片、旧 Office 格式优先走 API。
- 本地轻解析失败时，要允许自动降级，而不是硬失败。
