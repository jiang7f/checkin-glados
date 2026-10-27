"""Local account registry with atomic updates and private credential storage."""

import fcntl
import json
import os
import re
import shutil
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


class AccountError(Exception):
	pass


def validate_name(name: str) -> str:
	if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,47}', name):
		raise AccountError('账号名称须为 1–48 位英文字母、数字、下划线或短横线，并以字母或数字开头。')
	return name


@dataclass(frozen=True)
class Account:
	name: str
	cookie_header: str = field(repr=False)
	user_agent: str = field(repr=False)
	status: str = 'valid'
	verified_at: str = ''
	checked_at: str = ''


class AccountStore:
	def __init__(self, project_dir: Path):
		self.root = project_dir / '.accounts'
		self.path = self.root / 'accounts.json'
		self.profiles = project_dir / '.browser_profiles' / 'accounts'

	@property
	def exists(self) -> bool:
		return self.path.exists() or self.path.is_symlink() or self.root.is_symlink()

	def _ensure_root(self) -> None:
		if self.root.is_symlink() or self.path.is_symlink():
			raise AccountError('账号存储不能是符号链接。')
		self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
		self.root.chmod(0o700)

	@contextmanager
	def _lock(self, filename: str, *, blocking: bool = True):
		self._ensure_root()
		path = self.root / filename
		fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
		with os.fdopen(fd, 'a') as stream:
			try:
				fcntl.flock(stream, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
			except BlockingIOError:
				raise AccountError('该账号正在登录、签到或删除，请等待操作结束后重试。') from None
			try:
				yield
			finally:
				fcntl.flock(stream, fcntl.LOCK_UN)

	def account_lock(self, name: str):
		return self._lock(f'account-{validate_name(name).casefold()}.lock', blocking=False)

	def check_name(self, name: str) -> None:
		validate_name(name)
		if any(item.name != name and item.name.casefold() == name.casefold() for item in self.load()):
			raise AccountError('名称与已有账号仅大小写不同，请使用原名称或选择其他名称。')

	def profile_dir(self, name: str) -> Path:
		path = self.profiles / validate_name(name)
		if self.profiles.parent.is_symlink() or self.profiles.is_symlink() or path.is_symlink():
			raise AccountError('浏览器配置目录不能是符号链接。')
		return path

	def load(self) -> list[Account]:
		if self.root.is_symlink() or self.path.is_symlink():
			raise AccountError('账号存储不能是符号链接。')
		if not self.exists:
			return []
		try:
			data = json.loads(self.path.read_text(encoding='utf-8'))
			if not isinstance(data, dict) or data.get('version') != 1 or not isinstance(data.get('accounts'), dict):
				raise ValueError
			accounts = []
			seen = set()
			for name, value in data['accounts'].items():
				validate_name(name)
				if name.casefold() in seen:
					raise ValueError
				seen.add(name.casefold())
				if not isinstance(value, dict):
					raise ValueError
				cookie = value['cookie_header']
				agent = value['user_agent']
				if not isinstance(cookie, str) or not cookie or not isinstance(agent, str) or not agent:
					raise ValueError
				if any(ord(c) < 32 or ord(c) > 126 for c in cookie + agent):
					raise ValueError
				status = value.get('status', 'unknown')
				if status not in ('valid', 'expired', 'unknown'):
					raise ValueError
				if any(not isinstance(value.get(key, ''), str) for key in ('verified_at', 'checked_at')):
					raise ValueError
				accounts.append(
					Account(name, cookie, agent, status, value.get('verified_at', ''), value.get('checked_at', ''))
				)
			return accounts
		except (OSError, ValueError, KeyError, TypeError, AccountError):
			raise AccountError(
				'账号文件无法读取或格式无效，请恢复 .accounts/accounts.json 备份，勿直接覆盖。'
			) from None

	def _write(self, accounts: list[Account]) -> None:
		payload = {
			'version': 1,
			'accounts': {
				item.name: {
					'cookie_header': item.cookie_header,
					'user_agent': item.user_agent,
					'status': item.status,
					'verified_at': item.verified_at,
					'checked_at': item.checked_at,
				}
				for item in accounts
			},
		}
		fd, name = tempfile.mkstemp(prefix='.accounts-', dir=self.root)
		path = Path(name)
		try:
			with os.fdopen(fd, 'w', encoding='utf-8') as stream:
				json.dump(payload, stream, ensure_ascii=False, indent=2)
				stream.write('\n')
				stream.flush()
				os.fsync(stream.fileno())
			path.chmod(0o600)
			os.replace(path, self.path)
		finally:
			path.unlink(missing_ok=True)

	def save(self, name: str, cookie_header: str, user_agent: str, *, status: str = 'valid') -> None:
		validate_name(name)
		if status not in ('valid', 'expired', 'unknown'):
			raise AccountError('账号状态无效。')
		if not cookie_header or not user_agent or any(ord(c) < 32 or ord(c) > 126 for c in cookie_header + user_agent):
			raise AccountError('账号凭据格式无效。')
		with self._lock('registry.lock'):
			accounts = {item.name: item for item in self.load()}
			if any(existing != name and existing.casefold() == name.casefold() for existing in accounts):
				raise AccountError('名称与已有账号仅大小写不同，请使用原名称或选择其他名称。')
			accounts[name] = Account(
				name,
				cookie_header,
				user_agent,
				status,
				verified_at=datetime.now(timezone.utc).isoformat() if status == 'valid' else '',
			)
			self._write(list(accounts.values()))

	def mark(self, account: Account, status: str) -> None:
		if status not in ('valid', 'expired', 'unknown'):
			raise AccountError('账号状态无效。')
		with self._lock('registry.lock'):
			accounts = self.load()
			for index, current in enumerate(accounts):
				if (
					current.name == account.name
					and current.cookie_header == account.cookie_header
					and current.user_agent == account.user_agent
				):
					accounts[index] = Account(
						current.name,
						current.cookie_header,
						current.user_agent,
						status,
						current.verified_at,
						datetime.now(timezone.utc).isoformat(),
					)
					self._write(accounts)
					return

	def delete(self, name: str) -> bool:
		validate_name(name)
		with self.account_lock(name), self._lock('registry.lock'):
			accounts = self.load()
			if any(item.name != name and item.name.casefold() == name.casefold() for item in accounts):
				raise AccountError('账号名称大小写不匹配，请按 list 显示的名称操作。')
			profile = self.profile_dir(name)
			found = any(item.name == name for item in accounts)
			# Keep an empty registry so deleting the last account cannot reactivate legacy credentials.
			if found:
				self._write([item for item in accounts if item.name != name])
			if profile.exists():
				shutil.rmtree(profile)
			return found
