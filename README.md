# checkin-glados

本仓库是本地 GLaDOS 每日签到工具。脚本使用 GLaDOS cookie 调用签到接口，读取积分、连续签到天数和剩余天数，并通过飞书发送结果。

## 当前本地命令

```bash
checkin-glados
```

默认本地项目目录：

```bash
$HOME/仓库/checkin-glados
```

本地定时任务：

```text
com.checkin.glados  每天 10:10
```

仓库里的 `launchd/` 目录保存了当前机器使用的定时任务模板和安装说明。

## 环境配置

创建 `.env`：

```bash
cd "$HOME/仓库/checkin-glados"
cp .env.example .env
```

可以直接配置完整 cookie：

```dotenv
GLADOS_COOKIE=koa:sess=replace-with-session; koa:sess.sig=replace-with-signature
FEISHU_WEBHOOK=https://open.feishu.cn/open-apis/bot/v2/hook/xxx
```

也可以分开配置：

```dotenv
GLADOS_KOA_SESS=replace-with-session
GLADOS_KOA_SESS_SIG=replace-with-signature
FEISHU_WEBHOOK=https://open.feishu.cn/open-apis/bot/v2/hook/xxx
```

如果需要代理：

```dotenv
CHECKIN_PROXY_URL=http://127.0.0.1:7890
```

## 手动运行

```bash
checkin-glados
```

脚本会最多重试 5 次。如果接口返回今天已经签到，脚本会当作成功处理，不再重复重试。

## 飞书通知

通知标题：

```text
GLaDOS Check-in
```

通知示例：

```text
GLaDOS签到成功
时间: 2026-07-08 18:00:00

✅ 签到成功
消息: Checkin success
积分: 322
连续: 3 天
剩余: 324 天
```

## 本地定时任务

定时任务不是 Python 代码自动创建的，而是 macOS `launchd` 配置。仓库里的模板在：

```text
launchd/com.checkin.glados.plist
launchd/README.md
```

查看任务：

```bash
launchctl list | rg checkin
```

GLaDOS 当前每天 10:10 运行：

```text
~/Library/LaunchAgents/com.checkin.glados.plist
```

日志在：

```bash
~/Library/Logs/checkin-glados/stdout.log
~/Library/Logs/checkin-glados/stderr.log
```

## 依赖

```bash
uv sync --dev
```

日常运行只需要使用 `checkin-glados` 命令。

## 测试

```bash
uv run ruff check .
uv run pytest -q
```

## 安全说明

以下内容不会提交到 Git：

- `.env`
- `.env.*`
- `.venv/`
- coverage 和缓存目录
- `.DS_Store`

GitHub 仓库是 private，但仍然不要提交 cookie、webhook 或任何登录态。
