from unittest.mock import MagicMock

import httpx
import pytest
from playwright.sync_api import TimeoutError as BrowserTimeout

import browser_checkin
import checkin
from browser_cookie import BrowserSession, CookieImportError


def test_turnstile_challenge_uses_website_once_without_http_post(monkeypatch):
	calls = []

	def respond(request):
		assert request.method == 'GET'
		if request.url == checkin.CHALLENGE_URL:
			return httpx.Response(200, json={'code': 0, 'turnstile': {'sitekey': 'public'}})
		return httpx.Response(200, json={'code': 0, 'points': 838, 'data': {'leftDays': 248}})

	def website(cookie, **kwargs):
		calls.append((cookie, kwargs))
		return {'code': 0, 'message': 'Checkin success'}

	monkeypatch.setattr(checkin, 'browser_checkin', website)
	with httpx.Client(transport=httpx.MockTransport(respond)) as client:
		result = checkin.run_checkin(client, 'session=one', user_agent='AccountAgent', proxy='http://proxy:8080')
	assert result.success and result.points == 838
	assert calls == [('session=one', {'user_agent': 'AccountAgent', 'proxy': 'http://proxy:8080'})]


@pytest.mark.parametrize('browser_result', [
	{'code': 1, 'reason': 'turnstile', 'message': 'Cloudflare verification failed'},
	{'code': -1, 'message': '后台网页签到失败（TimeoutError）'},
])
def test_browser_failure_is_bounded_and_does_not_expire_credentials(monkeypatch, browser_result):
	website = MagicMock(return_value=browser_result)
	monkeypatch.setattr(checkin, 'browser_checkin', website)
	with httpx.Client(transport=httpx.MockTransport(
		lambda request: httpx.Response(200, json={'code': 0, 'turnstile': {'sitekey': 'public'}})
	)) as client:
		result = checkin.run_checkin(client, 'session=one', recovery_hint='checkin-glados add QQ')
	assert not result.success and not result.auth_failed
	assert 'add QQ' not in result.message
	website.assert_called_once()


def make_page(challenge=None):
	page = MagicMock()
	page.url = browser_checkin.PAGE_URL
	page.locator.return_value.is_disabled.return_value = False
	response = MagicMock(url=browser_checkin.CHALLENGE_URL, status=200)
	response.json.return_value = challenge or {'code': 0, 'turnstile': {'sitekey': 'public'}}
	page.goto.side_effect = lambda *args, **kwargs: page.on.call_args.args[1](response)
	return page


def test_page_clicks_only_daily_punch_and_returns_actual_post_result():
	page = make_page()
	response = MagicMock(url=browser_checkin.CHECKIN_URL, status=200)
	response.json.return_value = {'code': 0, 'message': 'Recorded', 'points': 14}
	page.expect_response.return_value.__enter__.return_value.value = response
	assert browser_checkin.submit_on_page(page) == response.json.return_value
	page.locator.assert_called_once_with('button.ckb')
	page.locator.return_value.click.assert_called_once()
	predicate = page.expect_response.call_args.args[0]
	assert predicate(MagicMock(url=browser_checkin.CHECKIN_URL, request=MagicMock(method='POST')))
	assert not predicate(MagicMock(url=browser_checkin.CHALLENGE_URL, request=MagicMock(method='GET')))
	page.remove_listener.assert_called_once()


def test_unfinished_turnstile_does_not_click_or_submit():
	page = make_page()
	page.wait_for_function.side_effect = [None, BrowserTimeout('verification needs interaction')]
	result = browser_checkin.submit_on_page(page)
	assert result['reason'] == 'turnstile'
	page.locator.return_value.click.assert_not_called()
	page.expect_response.assert_not_called()
	page.remove_listener.assert_called_once()


def test_login_redirect_is_reported_as_expired_without_submitting():
	page = make_page()
	page.url = 'https://glados.cloud/authenticate'
	assert browser_checkin.submit_on_page(page)['code'] == -2
	page.expect_response.assert_not_called()


def test_browser_contexts_keep_accounts_isolated_and_close_on_error(monkeypatch):
	import cloakbrowser

	browsers = [MagicMock(), MagicMock()]
	launch = MagicMock(side_effect=browsers)
	monkeypatch.setattr(cloakbrowser, 'launch', launch)
	monkeypatch.setattr(browser_checkin, 'configure_macos_background_browser', lambda: None)
	monkeypatch.setattr(browser_checkin, 'submit_on_page', MagicMock(side_effect=RuntimeError('private-cookie')))
	for name in ('one', 'two'):
		result = browser_checkin.browser_checkin(f'gld:sess={name}==; gld:sess.sig=sig', user_agent=name)
		assert 'private-cookie' not in result['message']
	for name, browser in zip(('one', 'two'), browsers):
		browser.new_context.assert_called_once_with(user_agent=name, locale='en-US')
		cookies = browser.new_context.return_value.add_cookies.call_args.args[0]
		assert cookies[0]['value'] == name + '=='
		browser.close.assert_called_once()
	assert all(call.kwargs['headless'] is True for call in launch.call_args_list)


def test_background_preparation_failure_never_launches_foreground_browser(monkeypatch):
	import cloakbrowser

	launch = MagicMock()
	monkeypatch.setattr(cloakbrowser, 'launch', launch)
	monkeypatch.setattr(browser_checkin, 'configure_macos_background_browser', MagicMock(side_effect=OSError()))
	assert browser_checkin.browser_checkin('session=x', user_agent='UA')['code'] == -1
	launch.assert_not_called()


@pytest.mark.parametrize('via_browser', [False, True])
def test_expired_session_has_account_relogin_command_in_terminal_and_feishu(monkeypatch, via_browser):
	monkeypatch.setattr(checkin, 'browser_checkin', lambda *a, **kw: {'code': -2})
	payload = {'code': 0, 'turnstile': True} if via_browser else {'code': -2}
	with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload))) as client:
		result = checkin.run_checkin(client, 'session=x', recovery_hint='请运行 checkin-glados add QQ 重新登录。')
	assert result.auth_failed and not result.success
	assert 'checkin-glados add QQ' in checkin.format_terminal_results([('QQ', result)])
	assert 'checkin-glados add QQ' in checkin.format_account_notification([('QQ', result)], execution_time='now')


def test_http_403_is_not_misreported_as_expired_during_login(monkeypatch):
	client = httpx.Client
	monkeypatch.setattr(checkin.httpx, 'Client', lambda **kw: client(
		transport=httpx.MockTransport(lambda r: httpx.Response(403))
	))
	with pytest.raises(CookieImportError):
		checkin.validate_session(BrowserSession('gld:sess', 'session', 'signature'))
