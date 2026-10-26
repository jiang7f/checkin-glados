# macOS 每日定时签到

模板默认每天 **运行机器本地时间 10:10** 执行一次 `checkin-glados`。它是当前用户的 LaunchAgent，用户登录后生效。先完成浏览器登录，并确认手动运行签到成功。

## 安装

在仓库根目录执行以下命令。先安装短命令，再生成定时任务配置：

```bash
uv run python scripts/install_command.py
mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs/checkin-glados"
uv run python - <<'PY'
import plistlib
from pathlib import Path

repo = Path.cwd()
user_dir = Path.home()
config = plistlib.loads((repo / 'launchd/com.checkin.glados.plist').read_bytes())
config['ProgramArguments'] = [str(user_dir / '.local/bin/checkin-glados')]
config['WorkingDirectory'] = str(repo)
config['StandardOutPath'] = str(user_dir / 'Library/Logs/checkin-glados/stdout.log')
config['StandardErrorPath'] = str(user_dir / 'Library/Logs/checkin-glados/stderr.log')
config['EnvironmentVariables']['PATH'] = config['EnvironmentVariables']['PATH'].replace('__HOME__', str(user_dir))
target = user_dir / 'Library/LaunchAgents/com.checkin.glados.plist'
target.write_bytes(plistlib.dumps(config))
print(target)
PY
plutil -lint "$HOME/Library/LaunchAgents/com.checkin.glados.plist"
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.checkin.glados.plist"
```

若任务已安装，先运行下面的 `bootout`，再重新 `bootstrap`。无需重新登录，也不必更改 `.env`：

```bash
launchctl bootout "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.checkin.glados.plist"
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.checkin.glados.plist"
```

## 验证和日志

```bash
launchctl print "gui/$(id -u)/com.checkin.glados"
tail -n 60 "$HOME/Library/Logs/checkin-glados/stdout.log"
tail -n 60 "$HOME/Library/Logs/checkin-glados/stderr.log"
```

立即触发一次任务（会签到，配置了飞书时也会发通知）：

```bash
launchctl kickstart "gui/$(id -u)/com.checkin.glados"
```

`last exit code = 0` 表示上次成功，`1` 表示签到失败，`2` 表示签到成功但飞书通知失败。未运行过的任务可能还没有退出码。

## 修改时间

编辑 `~/Library/LaunchAgents/com.checkin.glados.plist` 中 `StartCalendarInterval` 的 `Hour` 和 `Minute`，再执行上面的卸载 / 加载命令。例如 `Hour=8`、`Minute=30` 表示本机时间每天 08:30。

## 运行条件

- `launchd` 不读取交互终端的 `~/.zshrc`。登录、代理、飞书等应用配置应写在项目 `.env` 中。
- 任务不会自动启动代理软件。使用 `CHECKIN_PROXY_URL` 时，需要代理进程在运行。
- `RunAtLoad` 为 `false`，安装任务不会立即签到。
- 关机期间不会执行，睡眠期间的日历事件通常在唤醒后补触发。长时间关机不能保证每日签到。
- 登录失效时，手动运行 `checkin-glados login` 更新配置。日常定时任务不打开登录窗口。
- 项目移动后，请重新安装短命令、生成配置并重新加载任务。
- 日志会持续追加，需要定期自行归档或清理。

## 卸载

```bash
launchctl bootout "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.checkin.glados.plist"
rm "$HOME/Library/LaunchAgents/com.checkin.glados.plist"
```

卸载定时任务不删除项目、短命令或登录配置。
