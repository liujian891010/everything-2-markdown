# YouTube 处理流程

## 目标

把 YouTube URL 通过内部 `video2markdown` 服务转换成两阶段结果：

1. 先给用户一个基于 `key_points` 的简单简介
2. 再根据用户确认，决定是否用 `source_text` 按模板整理成正式 Markdown 文档

## API 规则

- 接口：`POST https://sg-al-cwork-web.mediportal.com.cn/video2markdown/parse`
- 鉴权：需要 token
- 处理方式：异步，必须等待成功态后再取结果

## 推荐步骤

1. 先确保拿到 token。
2. 调用 `video2markdown/parse` 提交 YouTube URL。
3. 若返回处理中，则持续轮询直到成功或超时。
4. 成功后读取返回中的 `key_points` 和 `source_text`。
5. 先把 `key_points` 组成简单简介，询问用户是否需要继续整理。
6. 只有在用户明确要求整理时，才使用 `source_text` 和 `references/report-template.md` 生成正式文档。
7. 正式文档生成后不要落盘到本地，而是先询问是否入库。

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
- 原始文本
- 入库确认问题与 docdb 元数据
