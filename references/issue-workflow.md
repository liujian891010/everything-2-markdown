# GitHub Issue 上报流程

## 目标

当用户在使用过程中发现问题、报错、体验缺陷或行为异常时，可以把反馈整理后主动提交到 GitHub Issue。

默认仓库：

- `https://github.com/liujian891010/everything-2-markdown`
- `repo = liujian891010/everything-2-markdown`

## 触发时机

- 用户明确在反馈 bug、错误、缺陷、异常行为。
- 用户希望“帮我提 issue”“帮我反馈到仓库”“把这个问题记到 GitHub”。
- 也可以在一次处理失败后，主动询问用户是否需要帮他提 issue。

## 处理入口

- `scripts/report_github_issue.py`

## 输入建议

尽量补齐这些信息：

- 问题描述
- 相关来源类型，例如 `youtube_url` / `douyin_url` / `uploaded_file`
- 原始输入
- 预期行为
- 实际行为
- 错误信息
- 环境信息

## GitHub 鉴权

- 使用 `--token`
- 或环境变量 `GITHUB_TOKEN`
- 或环境变量 `GH_TOKEN`

需要具备目标仓库的 issue 写权限。

如果没有 token：

- 不要伪装成“已创建成功”
- 要明确进入“向用户索要 token”分支
- 返回结构化提示，让调用侧去问用户要 token

## 输出

- `--dry-run` 时输出标准化 issue payload，供调用侧预览。
- 非 `--dry-run` 且有 token 时，直接创建 GitHub Issue，并返回：
  - `issue_number`
  - `issue_url`
  - `title`
- 非 `--dry-run` 且没有 token 时，返回：
  - `needs_user_token = true`
  - `question`
  - `payload`

## 注意

- 用户原始输入和错误日志应尽量保留，便于排查。
- 不要把无关的长篇正文整段塞进标题；标题应简洁。
