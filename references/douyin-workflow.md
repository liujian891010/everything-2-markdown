# 抖音处理流程

## 目标

把抖音 URL 通过 ASR 接口转换成两阶段结果：

1. 先给用户一个基于 `asr_text` 的简单简介
2. 再根据用户确认，决定是否按模板整理成正式 Markdown 报告

## API 规则

- 接口：`POST https://hk-al-xg-node.mediportal.com.cn/api/open/audio/export-with-asr`
- 鉴权：`Authorization: Bearer <token>`
- 返回：`asr_text` 即正文来源

## 推荐步骤

1. 调用 ASR 接口提交抖音 URL。
2. 读取返回中的 `asr_text`。
3. 基于 `asr_text` 生成简单简介和关键点。
4. 先给用户展示简介，并询问是否需要继续形成报告。
5. 只有在用户明确要求整理时，才使用 `asr_text` 和 `references/report-template.md` 生成正式文档。
6. 正式文档生成后不要落盘到本地，直接上传到 `cms-docdb`。

## 阶段 1 输出

- 标题
- 原始 URL
- 简单简介
- 追问：是否需要继续整理

## 阶段 2 输出

- 标题
- 简介
- 关键要点
- 正文整理
- docdb 元数据
