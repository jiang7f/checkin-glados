# GLaDOS 自动签到 · checkin-glados

[![Tests](https://github.com/jiang7f/checkin-glados/actions/workflows/tests.yml/badge.svg)](https://github.com/jiang7f/checkin-glados/actions/workflows/tests.yml)
[![Python](https://img.shields.io/badge/Python-3.11%2B-blue)](https://www.python.org/)
[![License](https://img.shields.io/github/license/jiang7f/checkin-glados)](LICENSE)

本地运行的 **GLaDOS 每日自动签到工具**。打开项目提供的独立浏览器，手动完成一次登录，脚本便会自动提取、验证并保存 Cookie。之后可直接签到，或通过 macOS 定时任务每日运行，将签到结果、积分、连续签到天数和剩余天数发送到飞书。

English summary — Local GLaDOS daily check-in automation with interactive browser login, automatic cookie capture, points tracking, macOS scheduling and Feishu bot notifications.

## 功能与适用范围

- **浏览器登录**：`login` 打开独立窗口，登录完成后自动保存 Cookie，无需手动复制。
- **其他登录方式**：从现有 Chrome 导入 Cookie，或自行填写 `.env`。
- **新旧登录态兼容**：优先使用 `gld:sess`，兼容旧版 `koa:sess`。
- **签到与查询**：调用签到接口，查询积分、连续天数和剩余天数。
- **重试与错误提示**：临时请求失败最多重试 5 次，鉴权失败立即停止。
- **飞书通知**：支持自定义机器人 Webhook、签名校验和独立通知测试。
- **本地定时运行**：提供 macOS `launchd` 模板，默认每天本机时间 10:10 执行。

目前以 **macOS 本地、单账号** 为验证环境。浏览器登录需要图形界面，首次安装会下载 CloakBrowser 浏览器运行时。日常签到使用 HTTP 请求，无需保持浏览器窗口打开。

仓库中的 GitHub Actions **只运行代码检查和测试**，不执行签到，也不会读取你的登录态。Fork 仓库不会自动帮你签到。暂未提供云端签到、Docker 或无界面服务器部署方案，Windows / Linux 也未作完整验证。

## 快速开始

### 1. 安装

需要 Python 3.11+、Git 和 [uv](https://docs.astral.sh/uv/getting-started/installation/)。macOS 可通过 Homebrew 安装 `uv`：

```bash
brew install uv
git clone https://github.com/jiang7f/checkin-glados.git
cd checkin-glados
uv sync --locked
uv run python -m cloakbrowser install
```

`uv` 会按项目要求选择 Python 和创建 `.venv`。更新 CloakBrowser 依赖后，请再次运行浏览器安装命令。

### 2. 创建配置

首次安装时执行，已有 `.env` 时保留原文件：

```bash
cp .env.example .env
chmod 600 .env
```

不需要代理、暂时不需要飞书通知时，可以保持示例配置不变，直接登录。

如需代理，先编辑 `.env`：

```dotenv
CHECKIN_PROXY_URL=http://127.0.0.1:7890
```

这里填写本地代理程序的 **HTTP / mixed 端口**，不是订阅链接。浏览器登录和 GLaDOS API 请求都会使用它。脚本不会自动启动代理程序。

### 3. 打开浏览器登录

```bash
uv run python checkin.py login
```

1. 等待独立浏览器打开 GLaDOS。
2. 在新窗口中按网站提供的方式登录，需要邮箱验证码或其他验证时自行完成。
3. 脚本检测到完整 Cookie 后，使用签到脚本相同的 HTTP 客户端查询状态接口。
4. 验证成功后自动更新 `.env`，保存浏览器 User-Agent，并关闭窗口。

默认等待 300 秒，慢网络或需要更多操作时可延长：

```bash
uv run python checkin.py login --timeout 600
```

登录成功会显示：

```text
[OK] 登录验证成功，已更新项目 .env。运行 checkin-glados 执行签到。
```

浏览器配置保存在项目的 `.browser_profiles/glados/`。这是独立配置，不使用日常 Chrome 的账号或钥匙串。下次运行 `login` 会复用该配置，已有有效登录态时会直接提取并关闭窗口。要更换 GLaDOS 账号，请在关闭登录浏览器后，将该目录移到 `.browser_profiles/` 下的另一个备份名称，再运行 `login` 并登录目标账号。

关闭登录窗口、按 `Ctrl+C`、登录超时或验证失败都不会覆盖原 `.env`。`login` 只更新登录态，不执行签到、不发送飞书通知。

### 4. 执行签到

```bash
uv run python checkin.py
```

如果只想签到、不发送通知：

```bash
uv run python checkin.py --no-notify
```

登录有效不等于签到已完成。只有签到接口明确返回成功，或明确表示今天已签到时，才判定本次运行成功。当天重复运行通常不会再增加积分，具体奖励由 GLaDOS 服务端决定。

### 5. 安装短命令（可选）

```bash
uv run python scripts/install_command.py
export PATH="$HOME/.local/bin:$PATH"
```

安装器会将当前项目路径和 `uv` 的绝对路径写入 `~/.local/bin/checkin-glados`。随后可以在任何目录执行：

```bash
checkin-glados login
checkin-glados
checkin-glados --no-notify
checkin-glados update-cookie
checkin-glados notify-test
```

将上面的 `export PATH=...` 加入 `~/.zshrc` 可使新终端也能找到命令。移动项目目录后，重新执行安装器，并更新已安装的定时任务。

## 三种登录方式

| 方式 | 命令或配置 | 适用情况 |
| --- | --- | --- |
| 独立浏览器，推荐 | `checkin-glados login` | 不想手动获取 Cookie，首次使用或登录失效 |
| 导入现有 Chrome | `checkin-glados update-cookie` | 已在日常 Chrome 登录 GLaDOS |
| 手动填写 | `.env` 中的 `GLADOS_COOKIE` | 已有可用 Cookie，或无法使用浏览器导入 |

未安装短命令时，将 `checkin-glados` 替换为项目目录中的 `uv run python checkin.py`。

### 从现有 Chrome 导入

先在 macOS Chrome 中登录 <https://glados.cloud>，再执行：

```bash
checkin-glados update-cookie
```

默认使用 Chrome 最近使用的配置。多个配置时，可在 `chrome://version` 查看“个人资料路径”，取最后的目录名：

```bash
checkin-glados update-cookie --profile "Profile 1"
```

此方式可能触发 macOS 的 `Chrome Safe Storage` 钥匙串授权。若数据库被占用，可以退出 Chrome 后重试，也可以改用不依赖 Chrome 钥匙串的 `login`。

仅提取 GLaDOS 的会话 Cookie，验证成功才保存，不打印 Cookie 内容。新旧 Cookie 共存时优先使用 `gld:sess` / `gld:sess.sig`，避免导入残留的旧登录态。

### 手动填写 Cookie

在浏览器开发者工具的 Network 面板找到已登录后的 GLaDOS 请求，从请求头获取 Cookie，保存到 `.env`：

```dotenv
GLADOS_COOKIE='gld:sess=replace-with-session; gld:sess.sig=replace-with-signature'
```

也可以分开填写：

```dotenv
GLADOS_GLD_SESS=replace-with-session
GLADOS_GLD_SESS_SIG=replace-with-signature
```

旧版登录态可使用 `GLADOS_KOA_SESS` / `GLADOS_KOA_SESS_SIG`。不要把新 `gld:sess` 的值填入旧版变量。

配置优先级为 `GLADOS_COOKIE` → 新版拆分配置 → 旧版拆分配置。Shell 中已设置的同名环境变量会覆盖 `.env`。如果更新后仍使用旧值，可先清除：

```bash
unset GLADOS_COOKIE GLADOS_GLD_SESS GLADOS_GLD_SESS_SIG GLADOS_KOA_SESS GLADOS_KOA_SESS_SIG GLADOS_USER_AGENT
```

登录导入会同时更新完整 Cookie 和对应拆分配置，移除不再使用的旧版登录变量，保留其他设置及注释，原子写入并将 `.env` 权限设为 `600`。

## 飞书机器人配置

飞书通知是可选功能。不填写 `FEISHU_WEBHOOK` 时，签到结果只显示在终端或定时任务日志中。

### 1. 创建自定义机器人

1. 打开用于接收通知的飞书群。
2. 进入群设置 → 机器人 → 添加机器人 → 自定义机器人。具体菜单名称可能随客户端版本不同。
3. 设置机器人名称，例如 `GLaDOS 签到`。
4. 复制机器人生成的 Webhook 地址，写入本地 `.env`：

```dotenv
FEISHU_WEBHOOK=https://open.feishu.cn/open-apis/bot/v2/hook/replace-with-your-token
```

使用的是群自定义机器人 Webhook，不需要 App ID、App Secret 或用户 Access Token。不要把 Webhook 提交到仓库或贴到 Issue。

### 2. 配置机器人安全设置

- **自定义关键词**：可设置 `GLaDOS`，签到通知和测试通知都包含该关键词。
- **签名校验**：如果启用，将机器人提供的签名密钥填入 `FEISHU_SECRET`。脚本会自动生成时间戳和签名。
- **IP 白名单**：如果启用，需要放行实际发出飞书请求的公网出口 IP。本机更换网络或代理出口后可能需要更新。

```dotenv
# 仅在飞书机器人启用了“签名校验”时填写
FEISHU_SECRET=replace-with-your-signing-secret
```

同时启用多项安全设置时，需要全部满足。`CHECKIN_PROXY_URL` 只用于 GLaDOS，不会强制让飞书走该代理。飞书 HTTP 客户端遵循系统进程中的 `HTTP_PROXY` / `HTTPS_PROXY` 等标准环境变量。

### 3. 测试通知

```bash
checkin-glados notify-test
```

这会向已配置的飞书群发送一条测试消息，不执行签到。看到 `[Feishu]: Message push successful!` 才表示飞书接口确认发送成功。

收到测试通知后，运行 `checkin-glados` 即可签到并发送结果。普通签到每次运行都会通知，包括今天已经签到的情况。

### 通知示例

```text
GLaDOS签到成功
时间: 2026-10-26 10:10:05

✅ 签到成功
消息: Checkin! Got 4 Points
积分: 493
连续: 1 天
剩余: 313 天
```

“积分”是当前总积分，不是本次增量。查询失败时对应字段会省略，不会伪造为 0。飞书发送成功只说明消息已送达，是否签到成功应看卡片中的状态和服务端消息。

签到成功后如果飞书发送失败，终端保留成功的签到结果并单独报告通知失败，不会重新签到，也不会再发送一条“签到失败”卡片。

## 每天自动签到（macOS）

先完成登录并确认手动签到成功，再安装短命令和定时任务。完整安装、修改时间、查看日志、卸载步骤见 [launchd 使用说明](launchd/README.md)。

默认每天 **运行机器本地时间 10:10** 执行。时区改变时，运行时刻也会按机器当前时区计算。只有用户登录后 LaunchAgent 才能工作；电脑关机时不会运行，睡眠期间的日历任务通常会在唤醒后补触发。

定时任务只运行签到脚本，不会打开登录窗口，也不会自动启动代理。登录失效时需要手动运行 `checkin-glados login`，更新后下次任务会自动读取 `.env`。

日志位置：

```text
~/Library/Logs/checkin-glados/stdout.log
~/Library/Logs/checkin-glados/stderr.log
```

## 配置参考

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `GLADOS_COOKIE` | 无 | 完整 Cookie，登录命令自动写入，优先级最高 |
| `GLADOS_GLD_SESS` / `GLADOS_GLD_SESS_SIG` | 无 | 新版会话的拆分配置，需要成对填写 |
| `GLADOS_KOA_SESS` / `GLADOS_KOA_SESS_SIG` | 无 | 旧版会话兼容配置 |
| `GLADOS_USER_AGENT` | 内置浏览器标识 | `login` 自动保存登录浏览器的标识，用于后续 API 请求 |
| `CHECKIN_PROXY_URL` | 无 | GLaDOS 登录及 API 请求的 HTTP 代理 |
| `FEISHU_WEBHOOK` | 无 | 飞书群机器人 Webhook，留空则不通知 |
| `FEISHU_SECRET` | 无 | 可选的飞书机器人签名密钥 |

所有命令固定读取项目目录下的 `.env`，不会因运行时所在目录不同而读取其他配置。

命令退出码：`0` 表示操作成功，`1` 表示签到、登录或通知测试失败，`2` 表示签到成功但飞书通知失败（参数使用错误也由命令解析器返回 `2`），交互登录按 `Ctrl+C` 返回 `130`。

## 常见问题

**浏览器已经登录，为什么仍提示“没有权限”？**

请确认是脚本打开的独立浏览器，还是日常 Chrome。两者登录态独立。日常 Chrome 登录后应使用 `update-cookie`，独立浏览器使用 `login`。GLaDOS 曾把会话名称从 `koa:sess` 改为 `gld:sess`，旧脚本会读到残留 Cookie，请先更新项目。还要检查 Shell 中是否有旧的登录环境变量。

**提示设备不匹配？**

运行 `checkin-glados login`，重新保存 Cookie 和对应 User-Agent。不要在其他设备与本机之间混用登录配置。如果网站仍拒绝请求，请在网站确认账号状态及当前服务规则。

**浏览器无法启动或页面空白？**

先运行 `uv run python -m cloakbrowser install`。确认当前是有图形桌面的本地会话，且没有另一个 `login` 使用同一配置目录。检查网络与 `.env` 中代理端口是否可连接，必要时延长 `--timeout`。

**收到飞书通知，积分却没增加？**

查看通知的签到结果和原始消息。今天已经签到不会重复领奖，`notify-test` 也不会签到。积分查询显示的是总积分。本站的奖励规则和发放结果以 GLaDOS 为准。

**飞书报错或收不到消息？**

先运行 `notify-test`。检查 Webhook 是否完整、机器人是否仍在群中、关键词是否为 `GLaDOS`、签名密钥是否一致、IP 白名单是否覆盖实际出口，以及系统时间是否准确。脚本会检查 HTTP 状态和飞书业务错误码。

**本地能运行，定时任务却失败？**

查看日志，检查绝对路径、`uv`、`.env` 以及代理进程。`launchd` 不读取交互式 Shell 的配置，建议把应用配置写进项目 `.env`，不要只在终端中 `export`。

**如何更新？**

```bash
git pull
uv sync --locked
uv run python -m cloakbrowser install
```

`.env` 和浏览器配置都不会被 Git 跟踪。移动项目目录后需要重新安装短命令和定时任务。

## 开发与反馈

```bash
uv sync --locked --dev
uv run ruff check .
uv run pytest -q
```

测试使用模拟凭据，不需要真实 Cookie 或飞书 Webhook，不会对真实账号签到。GitHub Actions 执行同样的检查。

提交问题请使用 [Issue 模板](https://github.com/jiang7f/checkin-glados/issues/new/choose)，说明操作系统、命令、登录方式、项目版本及脱敏后的错误日志。不要上传 `.env`、浏览器配置、Cookie、Webhook 或登录截图中的验证码。贡献步骤见 [CONTRIBUTING.md](CONTRIBUTING.md)，敏感信息处理见 [SECURITY.md](SECURITY.md)。

相关项目：[checkin-agentrouter](https://github.com/jiang7f/checkin-agentrouter)，提供 AgentRouter 本地浏览器登录签到。

本项目为第三方工具，与 GLaDOS 官方无关联。使用前请确认符合服务方当前规则。代码采用 [MIT License](LICENSE)。
