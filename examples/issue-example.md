# 示例：用户反馈问题并创建 GitHub Issue

用户输入：

```text
这个头条分享链接识别错了，明明是头条却被当成普通文本。帮我提个 issue 到仓库。
```

建议调用：

```bash
python scripts/report_github_issue.py \
  "头条分享文案中的短链没有被正确识别，导致输入被当成普通文本。" \
  --source-type toutiao_url \
  --input-value "【示例】点击链接打开 https://m.toutiao.com/is/xxxx/" \
  --expected "识别为 toutiao_url 并进入头条处理流程" \
  --actual "被识别为 plain_text，没有进入 URL 路由" \
  --error "detect_input 返回 kind=plain_text"
```

预期结果：

1. 如果已有 `GITHUB_TOKEN` 或 `GH_TOKEN`，直接创建 issue。
2. 如果没有 token，不创建 issue，返回 `needs_user_token = true` 和提问文案，调用侧应继续向用户索要 token。
3. 需要预览 payload 时，可额外加 `--dry-run`。
4. 默认仓库为 `liujian891010/everything-2-markdown`。
