"""Interactive login in a dedicated browser profile, with API validation before saving."""

import time
from collections.abc import Callable
from pathlib import Path

from browser_cookie import BrowserSession, CookieImportError, session_from_browser_cookies


class BrowserLoginError(Exception):
	pass


def wait_for_login(
	context, *, timeout: int, validate: Callable[[BrowserSession, str], bool]
) -> tuple[BrowserSession, str]:
	from playwright.sync_api import Error as PlaywrightError

	deadline = time.monotonic() + timeout
	last_candidate = None
	next_check = 0.0
	while time.monotonic() < deadline:
		pages = [page for page in context.pages if not page.is_closed()]
		if not pages:
			raise BrowserLoginError('登录窗口已关闭，原配置未更改。')
		try:
			session = session_from_browser_cookies(context.cookies('https://glados.cloud/api/user/status'))
		except CookieImportError:
			session = None
		if session is not None and (session != last_candidate or time.monotonic() >= next_check):
			try:
				user_agent = pages[0].evaluate('navigator.userAgent')
			except PlaywrightError:
				# Login redirects can replace the document while cookies are becoming available.
				user_agent = None
			if user_agent:
				if validate(session, user_agent):
					return session, user_agent
				last_candidate = session
				next_check = time.monotonic() + 5
		# Playwright's wait keeps browser events flowing while the user signs in.
		pages[0].wait_for_timeout(1000)
	raise BrowserLoginError('等待登录超时，原配置未更改。请重试 login，或使用 --timeout 600 延长等待。')


def capture_login(
	profile_dir: Path,
	*,
	timeout: int,
	proxy: str | None,
	validate: Callable[[BrowserSession, str], bool],
) -> tuple[BrowserSession, str]:
	from cloakbrowser import launch_persistent_context
	from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

	profile_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
	profile_dir.chmod(0o700)
	try:
		context = launch_persistent_context(str(profile_dir), headless=False, proxy=proxy)
	except Exception as exc:
		raise BrowserLoginError(
			f'无法启动登录浏览器（{type(exc).__name__}）。请运行 uv run python -m cloakbrowser install，'
			'并确认没有其他 login 命令正在使用同一配置目录。'
		) from None
	try:
		page = context.pages[0] if context.pages else context.new_page()
		try:
			page.goto('https://glados.cloud/console', wait_until='domcontentloaded', timeout=min(timeout, 60) * 1000)
		except PlaywrightTimeoutError:
			print('[INFO] 页面仍在加载，请在浏览器中完成登录；如页面空白，请检查代理。')
		return wait_for_login(context, timeout=timeout, validate=validate)
	finally:
		try:
			context.close()
		except Exception:
			pass
