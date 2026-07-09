# launchd

这个目录保存 macOS `launchd` 定时任务模板。当前模板每天 10:10 运行一次 `checkin-glados`。

安装：

```bash
mkdir -p ~/Library/Logs/checkin-glados
sed -e "s#__HOME__#$HOME#g" \
  -e "s#__REPO_DIR__#$(pwd)#g" \
  launchd/com.checkin.glados.plist > ~/Library/LaunchAgents/com.checkin.glados.plist
plutil -lint ~/Library/LaunchAgents/com.checkin.glados.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.checkin.glados.plist
```

查看：

```bash
launchctl list | rg com.checkin.glados
```

卸载：

```bash
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.checkin.glados.plist
rm ~/Library/LaunchAgents/com.checkin.glados.plist
```

模板里的 `__HOME__` 和 `__REPO_DIR__` 会在安装命令里替换成本机实际路径。
