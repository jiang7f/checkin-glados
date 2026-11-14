"""Submit through the current website when it requires browser verification."""

from urllib.parse import urlsplit

from macos_browser import configure_macos_background_browser

BASE_URL = 'https://glados.cloud'
PAGE_URL = f'{BASE_URL}/console/checkin'
CHECKIN_URL = f'{BASE_URL}/api/user/checkin'
CHALLENGE_URL = f'{CHECKIN_URL}/challenge'
VERIFICATION_MESSAGE = 'Cloudflare 网页验证未通过，本次未签到。请在官网签到页完成验证后重试。'


def verification_failure() -> dict:
	return {'code': -3, 'reason': 'turnstile', 'message': VERIFICATION_MESSAGE}


def response_payload(response) -> dict:
	if response.status >= 400:
		return {'code': response.status, 'message': f'HTTP {response.status}'}
	try:
		payload = response.json()
	except Exception:
		return {'code': -1, 'message': '官网返回了非 JSON 响应'}
	return payload if isinstance(payload, dict) else {'code': -1, 'message': '官网响应格式无效'}


def submit_on_page(page) -> dict:
	from playwright.sync_api import TimeoutError as BrowserTimeout

	challenges = []

	def observe(response):
		if response.url == CHALLENGE_URL:
			challenges.append(response_payload(response))

	page.on('response', observe)
	try:
		page.goto(PAGE_URL, wait_until='domcontentloaded', timeout=60_000)
		page.wait_for_function(
			"""() => document.querySelector('button.ckb') ||
				location.pathname === '/authenticate' || location.pathname === '/login'""",
			timeout=30_000,
		)
		if urlsplit(page.url).path.rstrip('/') in ('/authenticate', '/login'):
			return {'code': -2, 'message': '登录已过期'}
		button = page.locator('button.ckb')
		if button.is_disabled() and button.inner_text().strip() == 'Done for today':
			return {'code': 1, 'repeated': True, 'message': '今日已签到'}
		# Allow only the site's own widget to complete automatically. Never click
		# CAPTCHA controls or fabricate a verification token.
		deadline_ms = 30_000
		for _ in range(deadline_ms // 200):
			if challenges:
				break
			page.wait_for_timeout(200)
		if not challenges:
			return {'code': -1, 'message': '官网未加载签到挑战，本次未提交签到。'}
		challenge = challenges[-1]
		if challenge.get('code') != 0:
			return challenge
		if challenge.get('turnstile'):
			try:
				page.wait_for_function(
					"""() => [...document.querySelectorAll('input[name="cf-turnstile-response"]')]
						.some(input => input.value.length > 0)""",
					timeout=30_000,
				)
			except BrowserTimeout:
				return verification_failure()
		with page.expect_response(
			lambda response: response.url == CHECKIN_URL and response.request.method == 'POST',
			timeout=45_000,
		) as submitted:
			button.click(timeout=15_000)
		return response_payload(submitted.value)
	finally:
		page.remove_listener('response', observe)


def browser_checkin(cookie_header: str, *, user_agent: str, proxy: str | None = None) -> dict:
	from cloakbrowser import launch

	browser = None
	try:
		configure_macos_background_browser()
		browser = launch(headless=True, proxy=proxy, humanize=False)
		context = browser.new_context(user_agent=user_agent, locale='en-US')
		cookies = []
		for part in cookie_header.split(';'):
			name, separator, value = part.strip().partition('=')
			if separator and name:
				cookies.append({'name': name, 'value': value, 'url': BASE_URL})
		context.add_cookies(cookies)
		return submit_on_page(context.new_page())
	except Exception as exc:
		# Browser exceptions may include request data. Log only the exception type.
		return {'code': -1, 'message': f'后台网页签到失败（{type(exc).__name__}），请检查网络或官网页面。'}
	finally:
		if browser is not None:
			browser.close()
