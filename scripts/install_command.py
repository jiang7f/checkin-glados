"""Install a checkout-local command with absolute paths for shell and launchd use."""

import argparse
import shlex
import shutil
from pathlib import Path


def main() -> None:
	parser = argparse.ArgumentParser(description='安装 checkin-glados 短命令')
	parser.add_argument('--bin-dir', type=Path, default=Path.home() / '.local/bin')
	args = parser.parse_args()
	uv = shutil.which('uv')
	if uv is None:
		parser.error('未找到 uv，请先安装 uv 并加入 PATH')
	repo = Path(__file__).resolve().parent.parent
	args.bin_dir.mkdir(parents=True, exist_ok=True)
	target = args.bin_dir / 'checkin-glados'
	if target.is_symlink():
		parser.error('目标命令为符号链接，请先检查并移走该链接')
	target.write_text(
		'#!/bin/sh\nset -eu\n'
		f'cd {shlex.quote(str(repo))}\n'
		f'exec {shlex.quote(uv)} run --locked python checkin.py "$@"\n',
		encoding='utf-8',
	)
	target.chmod(0o755)
	print(f'已安装 {target}')
	print('请确认 ~/.local/bin 已加入 PATH。')


if __name__ == '__main__':
	main()
