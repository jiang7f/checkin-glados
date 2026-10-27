# GLaDOS 多账号自动签到 · checkin-glados

[![Tests](https://github.com/jiang7f/checkin-glados/actions/workflows/tests.yml/badge.svg)](https://github.com/jiang7f/checkin-glados/actions/workflows/tests.yml)
[![Python](https://img.shields.io/badge/Python-3.11%2B-blue)](https://www.python.org/)
[![License](https://img.shields.io/github/license/jiang7f/checkin-glados)](LICENSE)

本地运行的 **GLaDOS 多账号每日自动签到工具**。用 `add <名称>` 为每个账号打开独立浏览器，手动完成登录后自动提取、验证并保存 Cookie。直接运行命令即可并发签到全部已添加账号，也可通过 macOS 定时任务每日运行，将每个账号的结果、积分、连续签到天数和剩余天数汇总发送到飞书。

English summary — Local multi-account GLaDOS daily check-in with concurrent execution, isolated browser profiles, automatic cookie capture, points tracking, macOS scheduling and Feishu notifications.

## 功能与适用范围

- **多账号管理**：`add / list / delete`，命令习惯与 [checkin-agentrouter](https://github.com/jiang7f/checkin-agentrouter) 一致。
- **浏览器登录**：`add <名称>` 打开独立窗口，登录完成后自动保存 Cookie 和对应 User-Agent，无需手动复制。
- **并发签到**：默认最多同时签到 3 个账号，一个账号失败不影响其他账号，支持指定账号及并发数。
- **其他登录方式**：从现有 Chrome 导入 Cookie，或自行填写 `.env`。
- **新旧登录态兼容**：优先使用 `gld:sess`，兼容旧版 `koa:sess`。
- **签到与查询**：调用签到接口，查询积分、连续天数和剩余天数。
- **重试与错误提示**：临时请求失败最多重试 5 次，鉴权失败立即停止。
- **飞书通知**：支持自定义机器人 Webhook、签名校验和独立通知测试。
- **本地定时运行**：提供 macOS `launchd` 模板，默认每天本机时间 10:10 执行。

目前以 **macOS 本地运行** 为验证环境。每个账号有独立的浏览器配置和请求客户端。浏览器登录需要图形界面，首次安装会下载 CloakBrowser 浏览器运行时。日常签到使用 HTTP 请求，无需保持浏览器窗口打开。

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

### 3. 添加账号并登录

```bash
uv run python checkin.py add main
uv run python checkin.py add backup
uv run python checkin.py list
```

每条 `add` 命令执行完后，再执行下一条。只有一个账号时只需添加 `main`。`main`、`backup` 是你自己选的本地名称，不是网站的用户名或邮箱。

1. 等待该账号的独立浏览器打开 GLaDOS。
2. 在新窗口中按网站提供的方式登录，需要邮箱验证码或其他验证时自行完成。
3. 脚本检测到完整 Cookie 后，使用签到脚本相同的 HTTP 客户端查询状态接口。
4. 验证成功后保存该账号的 Cookie 和浏览器 User-Agent，并关闭窗口。

默认等待 300 秒，慢网络或需要更多操作时可延长：

```bash
uv run python checkin.py add main --timeout 600
```

登录成功会显示：

```text
[OK] main：登录已保存。
```

账号保存在 `.accounts/accounts.json`，浏览器配置保存在 `.browser_profiles/accounts/<名称>/`。两者均已被 Git 忽略。独立浏览器不使用日常 Chrome 的账号或钥匙串。再次运行 `add main` 会复用 `main` 的浏览器配置，已有有效登录态时会直接提取并关闭窗口。

添加另一个网站账号时应使用新名称并在新窗口登录。不要把同一网站账号用多个名称重复添加。关闭窗口、按 `Ctrl+C`、超时或验证失败都不会覆盖已保存的账号凭据。`add` 只更新登录态，不执行签到、不发送飞书通知。

### 4. 执行签到

```bash
uv run python checkin.py
uv run python checkin.py --account main
uv run python checkin.py --concurrency 2
```

以上分别为签到全部账号、仅签到 `main`、最多同时签到 2 个账号。如果只想签到、不发送通知：

```bash
uv run python checkin.py --no-notify
```

登录有效不等于签到已完成。只有签到接口明确返回成功，或明确表示今天已签到时，才判定本次运行成功。当天重复运行通常不会再增加积分，具体奖励由 GLaDOS 服务端决定。

终端按账号显示简要结果，失败时给出原因和处理命令。例如：

```text
正在签到…
[OK] main：签到成功 · 积分 493 · 连续 1 天 · 剩余 313 天
[OK] backup：今日已签到 · 积分 218 · 连续 4 天 · 剩余 127 天
完成：2/2 个账号成功。
[OK] 飞书已发送
```

### 5. 安装短命令（可选）

```bash
uv run python scripts/install_command.py
export PATH="$HOME/.local/bin:$PATH"
```

安装器会将当前项目路径和 `uv` 的绝对路径写入 `~/.local/bin/checkin-glados`。随后可以在任何目录执行：

```bash
checkin-glados add main
checkin-glados add backup
checkin-glados list
checkin-glados
checkin-glados --account main
checkin-glados --no-notify
checkin-glados update-cookie main
checkin-glados notify-test
```

将上面的 `export PATH=...` 加入 `~/.zshrc` 可使新终端也能找到命令。移动项目目录后，重新执行安装器，并更新已安装的定时任务。

## 账号管理与旧版迁移

| 命令 | 作用 |
| --- | --- |
| `checkin-glados add main` | 添加账号；名称已存在时验证并更新该账号登录态 |
| `checkin-glados login main` | 与 `add main` 等价 |
| `checkin-glados list` | 列出本地名称及最近记录的状态，不请求网站、不显示 Cookie |
| `checkin-glados delete main` | 删除该账号的本地凭据和对应浏览器目录，不注销网站账号 |
| `checkin-glados migrate main` | 将当前旧版 `.env` 登录配置复制为命名账号，保留原 `.env` |
| `checkin-glados` | 签到全部已添加账号，默认最多同时运行 3 个 |
| `checkin-glados --account main --no-notify` | 仅签到指定账号，并关闭本次飞书通知 |
| `checkin-glados --concurrency 2` | 将本次最大并发数改为 2 |

名称可用 1–48 位英文字母、数字、下划线和短横线，须以字母或数字开头。操作时使用 `list` 显示的原名称，不允许两个名称仅大小写不同。名称会出现在本地日志和飞书通知中，建议使用不含个人信息的简称。

`list` 中的状态是缓存，不代表当前实时状态：

- `有效`：最近一次登录验证或签到成功。
- `已过期`：签到接口明确返回登录失效（`-2` 或 `401`），用 `add <名称>` 重新登录。
- `未验证`：由旧配置迁移，尚未验证。临时网络错误、HTTP 403 或设备不匹配不会直接把账号标记为过期。

同一账号正在登录、签到或删除时，另一个操作会提示稍后重试，避免同时使用或删除浏览器配置。不同账号可以独立操作。

已有旧版 `.env` 登录配置时，先执行：

```bash
checkin-glados migrate main
checkin-glados list
checkin-glados --account main --no-notify
```

`migrate` 不执行网络验证、不刷新过期 Cookie，也不会覆盖同名账号。迁移后只签到账号列表中的记录，不会额外签到旧 `.env` 中的账号。飞书、代理和并发设置继续从 `.env` 读取，旧浏览器目录 `.browser_profiles/glados/` 也保留。

**首次成功添加或迁移账号后，会启用多账号模式。** 没有账号列表时，旧版 `.env` 单账号及不带名称的 `login` / `update-cookie` 仍可使用。启用后，登录和导入必须指定名称；即使删除最后一个账号也不会自动启用旧 Cookie。

## 三种登录方式

| 方式 | 命令或配置 | 适用情况 |
| --- | --- | --- |
| 独立浏览器，推荐 | `checkin-glados add main` | 不想手动获取 Cookie，首次使用或登录失效 |
| 导入现有 Chrome | `checkin-glados update-cookie main` | 已在日常 Chrome 登录 GLaDOS |
| 手动填写 | `.env` 中的 `GLADOS_COOKIE`，再运行 `migrate main` | 已有可用 Cookie，或无法使用浏览器导入 |

未安装短命令时，将 `checkin-glados` 替换为项目目录中的 `uv run python checkin.py`。

### 从现有 Chrome 导入

先在 macOS Chrome 中登录 <https://glados.cloud>，再执行：

```bash
checkin-glados update-cookie main
```

默认使用 Chrome 最近使用的配置。多个配置时，可在 `chrome://version` 查看“个人资料路径”，取最后的目录名：

```bash
checkin-glados update-cookie backup --profile "Profile 1"
```

此方式可能触发 macOS 的 `Chrome Safe Storage` 钥匙串授权。若数据库被占用，可以退出 Chrome 后重试，也可以改用不依赖 Chrome 钥匙串的 `add <名称>`。同一 Chrome 配置只会导入当前登录的网站账号；添加不同账号时应选择不同 Chrome 配置，或先在网站切换账号。

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

手动填写后运行 `checkin-glados migrate main`，再对该账号执行一次签到验证。如该名称已存在，请使用 `add main` 或 `update-cookie main` 更新。多账号模式使用各账号保存的 Cookie 和 User-Agent，不会被全局 `GLADOS_*` 变量覆盖。迁移时应同时配置登录浏览器对应的 `GLADOS_USER_AGENT`，设备不匹配时优先使用独立浏览器重新登录。

命名账号通过原子写入保存，`.accounts/` 权限为 `700`，账号文件权限为 `600`。只有旧版不带名称的登录命令会直接更新 `.env` 中的登录字段，保留其他设置及注释，并将 `.env` 权限设为 `600`。

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

这会向已配置的飞书群发送一条测试消息，不执行签到。看到 `[OK] 飞书已发送` 才表示飞书接口确认发送成功。

收到测试通知后，运行 `checkin-glados` 即可签到并发送结果。全部账号运行结束后汇总为一条通知，包含每个账号的名称、成功或失败原因和查询到的积分信息。所有账号共用 `.env` 中的飞书机器人。普通签到每次运行都会通知，包括今天已经签到的情况。

### 通知示例

```text
GLaDOS签到成功
时间: 2026-10-26 10:10:05
结果: 2/2

✅ main
消息: Checkin! Got 4 Points
积分: 493 | 连续: 1 天 | 剩余: 313 天

✅ backup
消息: Today's observation logged. Return tomorrow for more points.
积分: 218 | 连续: 4 天 | 剩余: 127 天
```

“积分”是当前总积分，不是本次增量。查询失败时对应字段会省略，不会伪造为 0。飞书发送成功只说明消息已送达，是否签到成功应看卡片中的状态和服务端消息。

签到成功后如果飞书发送失败，终端保留成功的签到结果并单独报告通知失败，不会重新签到，也不会再发送一条“签到失败”卡片。

## 每天自动签到（macOS）

先完成登录并确认手动签到成功，再安装短命令和定时任务。完整安装、修改时间、查看日志、卸载步骤见 [launchd 使用说明](launchd/README.md)。

默认每天 **运行机器本地时间 10:10** 执行。时区改变时，运行时刻也会按机器当前时区计算。只有用户登录后 LaunchAgent 才能工作；电脑关机时不会运行，睡眠期间的日历任务通常会在唤醒后补触发。

定时任务只运行签到脚本，不会打开登录窗口，也不会自动启动代理。已安装的任务会自动使用当前账号列表，添加账号后无需重新安装任务。登录失效时手动运行 `checkin-glados add <名称>`，更新后下次任务会读取新凭据。

日志位置：

```text
~/Library/Logs/checkin-glados/stdout.log
~/Library/Logs/checkin-glados/stderr.log
```

## 配置参考

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `GLADOS_COOKIE` | 无 | 旧版单账号或迁移来源的完整 Cookie，优先级最高 |
| `GLADOS_GLD_SESS` / `GLADOS_GLD_SESS_SIG` | 无 | 新版会话的拆分配置，需要成对填写 |
| `GLADOS_KOA_SESS` / `GLADOS_KOA_SESS_SIG` | 无 | 旧版会话兼容配置 |
| `GLADOS_USER_AGENT` | 内置浏览器标识 | 旧版单账号、手动迁移和 Chrome 导入时使用的浏览器标识；命名账号各自保存 |
| `CHECKIN_PROXY_URL` | 无 | GLaDOS 登录及 API 请求的 HTTP 代理 |
| `CHECKIN_CONCURRENCY` | `3` | 最大并发账号数，范围 1–32；`--concurrency` 优先于此配置 |
| `FEISHU_WEBHOOK` | 无 | 飞书群机器人 Webhook，留空则不通知 |
| `FEISHU_SECRET` | 无 | 可选的飞书机器人签名密钥 |

所有命令固定读取项目目录下的 `.env`，不会因运行时所在目录不同而读取其他配置。

命令退出码：`0` 表示操作成功，签到时须全部目标账号成功；`1` 表示至少一个账号签到失败，或登录、账号管理、通知测试失败；`2` 表示全部目标账号签到成功但飞书通知失败（参数使用错误也由命令解析器返回 `2`）；交互登录按 `Ctrl+C` 返回 `130`。

## 常见问题

**浏览器已经登录，为什么仍提示“没有权限”？**

请确认是脚本打开的独立浏览器，还是日常 Chrome。两者登录态独立。日常 Chrome 登录后应使用 `update-cookie <名称>` 并选对 Chrome 配置，独立浏览器使用 `add <名称>`。GLaDOS 曾把会话名称从 `koa:sess` 改为 `gld:sess`，旧脚本会读到残留 Cookie，请先更新项目。若 Chrome 导入仍失败，使用 `add <名称>` 重新登录并同步保存 Cookie 与浏览器标识。旧版单账号还要检查 Shell 中是否有旧的登录环境变量。

**提示设备不匹配？**

运行 `checkin-glados add <名称>`，重新保存该账号的 Cookie 和对应 User-Agent。不要在其他设备与本机之间混用登录配置。如果网站仍拒绝请求，请在网站确认账号状态及当前服务规则。

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

`.env`、`.accounts/` 和浏览器配置都不会被 Git 跟踪，更新前也建议自行保留私密备份。移动项目目录后需要重新安装短命令和定时任务。

## 开发与反馈

```bash
uv sync --locked --dev
uv run ruff check .
uv run pytest -q
```

测试使用模拟凭据，不需要真实 Cookie 或飞书 Webhook，不会对真实账号签到。GitHub Actions 执行同样的检查。

提交问题请使用 [Issue 模板](https://github.com/jiang7f/checkin-glados/issues/new/choose)，说明操作系统、命令、登录方式、项目版本及脱敏后的错误日志。不要上传 `.env`、`.accounts/`、浏览器配置、Cookie、Webhook 或登录截图中的验证码；账号名称也应替换为通用示例。贡献步骤见 [CONTRIBUTING.md](CONTRIBUTING.md)，敏感信息处理见 [SECURITY.md](SECURITY.md)。

相关项目：[checkin-agentrouter](https://github.com/jiang7f/checkin-agentrouter)，提供 AgentRouter 本地浏览器登录签到。

本项目为第三方工具，与 GLaDOS 官方无关联。使用前请确认符合服务方当前规则。代码采用 [MIT License](LICENSE)。
