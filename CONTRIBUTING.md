# 贡献指南

欢迎提交问题、改进文档或修复代码。项目当前以 macOS 本地单账号运行为验证范围，新增平台、云端部署或多账号支持前，建议先在 Issue 中说明方案。

## 本地开发

```bash
git clone https://github.com/jiang7f/checkin-glados.git
cd checkin-glados
uv sync --locked --dev
uv run ruff check .
uv run pytest -q
```

浏览器功能的实际运行还需要 `uv run python -m cloakbrowser install`。测试使用模拟数据，不要求登录真实账号。

## 提交变更

1. 从 `main` 创建功能分支。
2. 保持改动聚焦，为登录、签到判断、凭据保存和通知错误处理等行为补充回归测试。
3. 新增配置或命令时同步更新 README 和 `.env.example`。
4. 运行代码检查、测试及 `git diff --check`。
5. 在 Pull Request 中说明问题、行为变化及验证方式。

遵循现有代码的 Tab 缩进与单引号风格。不要提交 `.env`、真实 Cookie、Webhook、浏览器配置、账号截图或运行日志。模拟凭据应使用明确的 `example` / `test` 值。

修改依赖时使用 `uv add` / `uv remove` 并提交 `uv.lock`。GitHub Actions 只做测试，不允许在测试中读取真实账号或发送真实通知。
