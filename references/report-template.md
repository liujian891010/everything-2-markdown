# Report Template

用于把来源内容整理成标准 Markdown 文档。当前 `everything-2-markdown` 的 YouTube 分支直接读取这个模板并填充。

```markdown
# {title}

> 来源：{source_platform}
> 链接：{source_url}
> 整理日期：{report_date}

---

## 简介
{summary}

## 关键要点
{key_points_bullets}

## 正文整理
{organized_body}

## 原始文本
{source_text_block}
```

## 字段说明

- `title`：文档标题，优先使用接口返回标题；无标题时降级为来源名称。
- `source_platform`：来源平台，例如 `YouTube`。
- `source_url`：原始链接。
- `report_date`：生成日期，格式 `YYYY-MM-DD`。
- `summary`：基于 `key_points` 生成的简单简介。
- `key_points_bullets`：将关键点整理成 Markdown 无序列表。
- `organized_body`：基于 `source_text` 的正文整理结果。
- `source_text_block`：原始文本，放在代码块中保留。
