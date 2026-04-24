# 来源识别与路由规则

## 路由优先级

1. 明确是文件路径或用户声明“上传文件”时，走文件处理。
2. 是 `youtube.com` / `youtu.be` 时，走 YouTube 处理。
3. 是 `douyin.com` / `v.douyin.com` 时，走抖音处理。
4. 是 `toutiao.com` / `ixigua.com` 时，走头条处理。
5. 其他 `http(s)` 链接，走通用 URL 处理。
6. 如果输入不是单独的 URL，而是分享文案、口令、标题加链接，先从整段文本中提取第一个合法 `http(s)` 链接，再按域名继续路由。
7. 如果提取到的是已知分享短链，则先自动跟跳拿到最终落地 URL，再把最终 URL 交给后续脚本：
   - `v.douyin.com/...`
   - `m.toutiao.com/is/...`
8. 都不满足时，视为纯文本或聊天记录，走文本总结流程。

## 不要混用

- 不要把 YouTube 当普通网页处理。
- 不要把抖音分享短链当普通 URL 处理。
- 不要把头条分享短链当普通博客页处理。
- 不要把本地文件路径误判成普通文本。
- 不要把聊天记录误送到 URL 或文件流程。

## 返回格式

识别脚本统一输出 JSON，至少包含：

- `kind`
- `route`
- `input`
- 与来源相关的附加字段，例如 `host`、`file_kind`、`exists`

如果是从分享文案中抽取 URL，补充：

- `detected_from_embedded_url`
- `original_input`

如果是短链自动跟跳，补充：

- `resolved_from_short_url`
- `original_short_url`
