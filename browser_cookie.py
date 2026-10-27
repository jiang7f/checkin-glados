import json
import os
import tempfile
from dataclasses import dataclass, field
from http.cookiejar import Cookie, CookieJar
from pathlib import Path

from dotenv import dotenv_values, set_key, unset_key


class CookieImportError(Exception):
	"""An actionable import error that does not contain cookie values."""


@dataclass(frozen=True)
class BrowserSession:
	cookie_name: str
	session: str = field(repr=False)
	signature: str = field(repr=False)

	@property
	def cookie_header(self) -> str:
		return f'{self.cookie_name}={self.session}; {self.cookie_name}.sig={self.signature}'


def chrome_cookie_file(profile: str | None = None, *, user_data_dir: Path | None = None) -> Path:
	root = user_data_dir or Path.home() / 'Library/Application Support/Google/Chrome'
	if profile is None:
		try:
			state = json.loads((root / 'Local State').read_text(encoding='utf-8'))
			profile = state.get('profile', {}).get('last_used') or 'Default'
		except (OSError, ValueError):
			profile = 'Default'
	if not isinstance(profile, str) or Path(profile).name != profile or profile in ('.', '..'):
		raise CookieImportError('Chrome 配置名无效，请使用 Default 或 Profile 1。')
	for relative in ('Network/Cookies', 'Cookies'):
		path = root / profile / relative
		if path.is_file():
			return path
	raise CookieImportError('未找到 Chrome 登录数据，请先登录或用 --profile 指定配置。')


def session_from_cookies(cookies: CookieJar) -> BrowserSession:
	groups: dict[tuple[str, str], dict[str, str]] = {}
	for cookie in cookies:
		if cookie.domain.lstrip('.') != 'glados.cloud' or cookie.is_expired():
			continue
		if cookie.name not in ('gld:sess', 'gld:sess.sig', 'koa:sess', 'koa:sess.sig'):
			continue
		if not '/api/user/status'.startswith(cookie.path.rstrip('/') + '/'):
			continue
		groups.setdefault((cookie.domain, cookie.path), {})[cookie.name] = cookie.value
	# GLaDOS migrated to gld:sess. Chrome may retain the obsolete koa:sess pair.
	for name in ('gld:sess', 'koa:sess'):
		pairs = {
			(values[name], values[f'{name}.sig'])
			for values in groups.values()
			if name in values and f'{name}.sig' in values
		}
		if not pairs:
			continue
		if len(pairs) != 1:
			raise CookieImportError('发现多个 GLaDOS 登录态，请清理网站 Cookie 后重新登录。')
		session, signature = pairs.pop()
		if any(
			not value or any(ord(c) <= 32 or ord(c) >= 127 or c == ';' for c in value) for value in (session, signature)
		):
			raise CookieImportError('Chrome 中的 GLaDOS Cookie 格式无效，请重新登录。')
		return BrowserSession(name, session, signature)
	raise CookieImportError('未找到完整登录态，请在 Chrome 登录 GLaDOS 后重试。')


def read_chrome_session(profile: str | None = None) -> BrowserSession:
	import browser_cookie3

	path = chrome_cookie_file(profile)
	try:
		cookies = browser_cookie3.chrome(cookie_file=str(path), domain_name='glados.cloud')
	except Exception as exc:
		raise CookieImportError(
			f'Chrome 导入失败（{type(exc).__name__}），请检查钥匙串授权或退出 Chrome 后重试。'
		) from None
	return session_from_cookies(cookies)


def session_from_browser_cookies(cookies: list[dict]) -> BrowserSession:
	jar = CookieJar()
	for item in cookies:
		expires = item.get('expires', -1)
		jar.set_cookie(
			Cookie(
				version=0,
				name=item['name'],
				value=item['value'],
				port=None,
				port_specified=False,
				domain=item['domain'],
				domain_specified=True,
				domain_initial_dot=item['domain'].startswith('.'),
				path=item.get('path', '/'),
				path_specified=True,
				secure=item.get('secure', True),
				expires=expires if expires > 0 else None,
				discard=expires <= 0,
				comment=None,
				comment_url=None,
				rest={},
			)
		)
	return session_from_cookies(jar)


def save_session(env_path: Path, session: BrowserSession, *, user_agent: str | None = None) -> None:
	if env_path.is_symlink():
		raise CookieImportError('.env 是符号链接，请先将其改为项目内的普通文件后重试。')
	prefix = 'GLADOS_GLD' if session.cookie_name == 'gld:sess' else 'GLADOS_KOA'
	values = {
		'GLADOS_COOKIE': session.cookie_header,
		f'{prefix}_SESS': session.session,
		f'{prefix}_SESS_SIG': session.signature,
	}
	if user_agent:
		values['GLADOS_USER_AGENT'] = user_agent
	content = env_path.read_text(encoding='utf-8') if env_path.exists() else ''
	fd, name = tempfile.mkstemp(prefix='.env.import-', dir=env_path.parent)
	temporary = Path(name)
	try:
		with os.fdopen(fd, 'w', encoding='utf-8') as stream:
			stream.write(content)
		existing_keys = dotenv_values(temporary).keys()
		for key, value in values.items():
			set_key(temporary, key, value)
		for key in ('GLADOS_GLD_SESS', 'GLADOS_GLD_SESS_SIG', 'GLADOS_KOA_SESS', 'GLADOS_KOA_SESS_SIG'):
			if key not in values and key in existing_keys:
				unset_key(temporary, key)
		temporary.chmod(0o600)
		os.replace(temporary, env_path)
	finally:
		temporary.unlink(missing_ok=True)
