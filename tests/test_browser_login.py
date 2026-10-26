from types import SimpleNamespace

import pytest
from dotenv import dotenv_values

import browser_login
import checkin
from browser_cookie import BrowserSession, session_from_browser_cookies


def cookies(session='example-session'):
	return [
		{'name': name, 'value': value, 'domain': 'glados.cloud', 'path': '/', 'expires': -1, 'secure': True}
		for name, value in [('gld:sess', session), ('gld:sess.sig', 'example-signature')]
	]


class FakePage:
	def __init__(self, clock):
		self.clock = clock
		self.closed = False

	def is_closed(self):
		return self.closed

	def evaluate(self, expression):
		assert expression == 'navigator.userAgent'
		return 'Browser test agent'

	def wait_for_timeout(self, ms):
		self.clock[0] += ms / 1000

	def goto(self, url, **kwargs):
		assert url == 'https://glados.cloud/console'


@pytest.fixture
def context(monkeypatch):
	clock = [0.0]
	monkeypatch.setattr(browser_login.time, 'monotonic', lambda: clock[0])
	page = FakePage(clock)
	return SimpleNamespace(pages=[page], cookies=lambda url: cookies(), close=lambda: None)


def test_waits_for_verified_session_instead_of_cookie_presence(context):
	calls = []

	def validate(session, agent):
		calls.append((session, agent))
		return len(calls) == 2

	session, agent = browser_login.wait_for_login(context, timeout=20, validate=validate)
	assert session.cookie_name == 'gld:sess'
	assert agent == 'Browser test agent'
	assert len(calls) == 2
	assert context.pages[0].clock[0] == 5


def test_captures_cookie_created_after_user_logs_in(context):
	context.cookies = lambda url: cookies() if context.pages[0].clock[0] >= 2 else []
	session, _ = browser_login.wait_for_login(context, timeout=10, validate=lambda *args: True)
	assert session.session == 'example-session'
	assert context.pages[0].clock[0] == 2


def test_rejected_session_times_out_without_returning_credentials(context):
	with pytest.raises(browser_login.BrowserLoginError, match='超时'):
		browser_login.wait_for_login(context, timeout=2, validate=lambda *args: False)


def test_closing_window_cancels_login(context):
	context.pages[0].closed = True
	with pytest.raises(browser_login.BrowserLoginError, match='关闭'):
		browser_login.wait_for_login(context, timeout=2, validate=lambda *args: True)


def test_login_redirect_does_not_abort_cookie_capture(context):
	from playwright.sync_api import Error

	def evaluate(expression):
		if context.pages[0].clock[0] == 0:
			raise Error('Execution context was destroyed')
		return 'Browser test agent'

	context.pages[0].evaluate = evaluate
	assert browser_login.wait_for_login(context, timeout=5, validate=lambda *args: True)[1] == 'Browser test agent'


@pytest.mark.parametrize('valid', [True, False])
def test_browser_closes_on_success_and_timeout(monkeypatch, tmp_path, context, valid):
	import cloakbrowser

	closed = []
	context.close = lambda: closed.append(True)

	def launch(profile, **kwargs):
		assert kwargs == {'headless': False, 'proxy': 'http://localhost:7890'}
		return context

	monkeypatch.setattr(cloakbrowser, 'launch_persistent_context', launch)

	def capture():
		return browser_login.capture_login(
			tmp_path / 'profile', timeout=1, proxy='http://localhost:7890', validate=lambda *args: valid
		)

	if valid:
		assert capture()[0].cookie_name == 'gld:sess'
	else:
		with pytest.raises(browser_login.BrowserLoginError):
			capture()
	assert closed == [True]


def test_browser_cookie_conversion_filters_foreign_and_expired_credentials():
	items = cookies()
	items.extend([dict(items[0], domain='other.example'), dict(items[0], path='/console')])
	assert session_from_browser_cookies(items).cookie_name == 'gld:sess'


@pytest.mark.parametrize('fail', [False, True])
def test_login_command_saves_verified_credentials_and_ua_only(monkeypatch, tmp_path, capsys, fail):
	path = tmp_path / '.env'
	original = '# config\nFEISHU_WEBHOOK=placeholder\n'
	path.write_text(original)
	monkeypatch.setattr(checkin, 'ENV_PATH', path)
	monkeypatch.setattr(checkin, 'load_dotenv', lambda *args: None)
	monkeypatch.setattr(checkin, 'send_feishu', lambda *args: pytest.fail('Login must not notify'))
	monkeypatch.setattr(checkin, 'run_checkin', lambda *args: pytest.fail('Login must not check in'))

	def capture(*args, **kwargs):
		assert kwargs['timeout'] == 60
		if fail:
			raise browser_login.BrowserLoginError('等待登录超时')
		return BrowserSession('gld:sess', 'private-session', 'private-signature'), 'Browser test agent'

	monkeypatch.setattr(browser_login, 'capture_login', capture)
	assert checkin.cli(['login', '--timeout', '60']) == int(fail)
	if fail:
		assert path.read_text() == original
	else:
		config = dotenv_values(path)
		assert config['GLADOS_USER_AGENT'] == 'Browser test agent'
		assert config['GLADOS_COOKIE'] == 'gld:sess=private-session; gld:sess.sig=private-signature'
		assert config['FEISHU_WEBHOOK'] == 'placeholder'
	assert 'private-session' not in capsys.readouterr().out


def test_login_rejects_invalid_timeout():
	with pytest.raises(SystemExit) as exc:
		checkin.cli(['login', '--timeout', '0'])
	assert exc.value.code == 2
