import threading

import httpx
import pytest

import browser_cookie
import browser_login
import checkin
from accounts import AccountStore
from browser_cookie import BrowserSession


@pytest.fixture
def store(tmp_path):
	return AccountStore(tmp_path)


def test_named_login_uses_independent_profiles_and_preserves_env(monkeypatch, store, capsys):
	original = 'FEISHU_WEBHOOK=example-preserved\n'
	checkin.ENV_PATH.write_text(original)
	profiles = []

	def capture(path, **kwargs):
		profiles.append(path)
		assert kwargs['timeout'] == 60
		return BrowserSession('gld:sess', f'example-{path.name}', 'example-signature'), f'ExampleAgent-{path.name}'

	monkeypatch.setattr(browser_login, 'capture_login', capture)
	for name in ('main', 'backup'):
		assert checkin.cli(['add', name, '--timeout', '60']) == 0
	assert profiles == [store.profile_dir('main'), store.profile_dir('backup')]
	assert [a.user_agent for a in store.load()] == ['ExampleAgent-main', 'ExampleAgent-backup']
	assert checkin.ENV_PATH.read_text() == original
	assert 'example-signature' not in capsys.readouterr().out


def test_failed_relogin_preserves_previous_session(monkeypatch, store):
	store.save('main', 'example-original', 'ExampleAgent')
	original = store.path.read_bytes()

	def fail(*args, **kwargs):
		raise browser_login.BrowserLoginError('等待登录超时')

	monkeypatch.setattr(browser_login, 'capture_login', fail)
	assert checkin.cli(['add', 'main']) == 1
	assert store.path.read_bytes() == original


def test_case_conflict_and_busy_account_do_not_launch_browser(monkeypatch, store):
	store.save('Main', 'example-original', 'ExampleAgent')
	monkeypatch.setattr(
		browser_login, 'capture_login', lambda *args, **kwargs: pytest.fail('must reject before launch')
	)
	assert checkin.cli(['add', 'main']) == 1
	with store.account_lock('Main'):
		assert checkin.cli(['add', 'Main']) == 1
		assert checkin.cli(['delete', 'Main']) == 1


def test_chrome_import_into_named_account_keeps_global_configuration(monkeypatch, store):
	original = 'GLADOS_COOKIE=example-old\nFEISHU_WEBHOOK=example-preserved\n'
	checkin.ENV_PATH.write_text(original)
	seen = []

	def read(profile):
		seen.append(profile)
		return BrowserSession('gld:sess', 'example-main', 'example-signature')

	monkeypatch.setattr(browser_cookie, 'read_chrome_session', read)
	monkeypatch.setattr(checkin, 'validate_session', lambda *args: True)
	assert checkin.cli(['update-cookie', 'main', '--profile', 'Profile 1']) == 0
	assert seen == ['Profile 1']
	assert store.load()[0].cookie_header == 'gld:sess=example-main; gld:sess.sig=example-signature'
	assert checkin.ENV_PATH.read_text() == original


def test_migrate_preserves_legacy_configuration_and_does_not_overwrite(store, capsys):
	original = 'GLADOS_COOKIE=example-legacy-cookie\nGLADOS_USER_AGENT=ExampleAgent\n'
	checkin.ENV_PATH.write_text(original)
	assert checkin.cli(['migrate', 'main']) == 0
	(account,) = store.load()
	assert account.name == 'main' and account.status == 'unknown'
	assert account.cookie_header == 'example-legacy-cookie'
	assert account.user_agent == 'ExampleAgent'
	assert checkin.ENV_PATH.read_text() == original
	before = store.path.read_bytes()
	assert checkin.cli(['migrate', 'main']) == 1
	assert store.path.read_bytes() == before
	assert 'example-legacy-cookie' not in capsys.readouterr().out


def test_list_is_local_and_never_exposes_credentials(monkeypatch, store, capsys):
	store.save('main', 'example-private-cookie', 'ExampleAgent')
	monkeypatch.setattr(checkin.httpx, 'Client', lambda **kw: pytest.fail('list must not access network'))
	assert checkin.cli(['list']) == 0
	output = capsys.readouterr().out
	assert 'main  (saved, valid)' in output
	assert 'example-private-cookie' not in output


@pytest.mark.parametrize('command', [['login'], ['update-cookie']])
def test_multi_account_mode_requires_target_for_login(store, command):
	store.save('main', 'example-cookie', 'ExampleAgent')
	assert checkin.cli(command) == 1


@pytest.mark.parametrize('state', ['empty', 'corrupt', 'missing-selected'])
def test_multi_account_errors_cannot_reactivate_legacy_login(monkeypatch, store, state):
	monkeypatch.setenv('GLADOS_COOKIE', 'example-legacy')
	monkeypatch.setattr(checkin, 'run_checkin', lambda *args, **kw: pytest.fail('must not use legacy credentials'))
	store.save('main', 'example-cookie', 'ExampleAgent')
	if state == 'empty':
		store.delete('main')
	elif state == 'corrupt':
		store.path.write_text('invalid')
	assert checkin.main(selected='missing' if state == 'missing-selected' else None) == 1


@pytest.mark.parametrize('selected,concurrency', [('', None), ('main', 0), ('main', 33)])
def test_invalid_selection_and_concurrency_make_no_requests(monkeypatch, store, selected, concurrency):
	store.save('main', 'example-cookie', 'ExampleAgent')
	monkeypatch.setattr(checkin, 'run_accounts', lambda *args, **kw: pytest.fail('invalid input'))
	assert checkin.main(selected=selected, concurrency=concurrency) == 1


def test_worker_limit_stable_order_and_exception_isolation(monkeypatch, store):
	for name in ('main', 'backup', 'extra', 'last'):
		store.save(name, f'example-{name}', 'ExampleAgent')
	barrier = threading.Barrier(2, timeout=5)
	lock = threading.Lock()
	active = 0
	peak = 0

	def worker(account, *args):
		nonlocal active, peak
		with lock:
			active += 1
			peak = max(peak, active)
		try:
			barrier.wait()
			if account.name == 'main':
				raise RuntimeError('example-private-cookie')
			return checkin.CheckinResult(True, 'Success')
		finally:
			with lock:
				active -= 1

	monkeypatch.setattr(checkin, 'run_account', worker)
	results = checkin.run_accounts(store.load(), store, concurrency=2, proxy=None)
	assert peak == 2
	assert [name for name, _ in results] == ['main', 'backup', 'extra', 'last']
	assert [result.success for _, result in results] == [False, True, True, True]
	assert 'example-private-cookie' not in results[0][1].message


def test_clients_headers_and_auth_status_are_isolated(monkeypatch, store, capsys):
	names = ('good', 'expired', 'blocked', 'network', 'device')
	for name in names:
		store.save(name, f'gld:sess=example-{name}', f'ExampleAgent-{name}')
	store.mark(store.load()[0], 'expired')
	monkeypatch.setenv('GLADOS_COOKIE', 'example-wrong-global-cookie')
	monkeypatch.setenv('GLADOS_USER_AGENT', 'ExampleWrongGlobalAgent')
	client_class = httpx.Client
	clients = []
	seen = []

	def factory(**kwargs):
		requests = []

		def respond(request):
			name = request.headers['User-Agent'].removeprefix('ExampleAgent-')
			requests.append(name)
			assert name in names
			assert request.headers['Cookie'] == f'gld:sess=example-{name}'
			seen.append((name, request.url.path))
			if name == 'expired':
				return httpx.Response(200, json={'code': -2, 'message': 'Unauthorized'})
			if name == 'blocked':
				return httpx.Response(403)
			if name == 'network':
				raise httpx.ConnectError('example-private-cookie')
			if name == 'device':
				return httpx.Response(200, json={'code': 4, 'reason': 'device-mismatch'})
			return httpx.Response(200, json={'code': 0, 'message': 'Success', 'points': 100, 'data': {'leftDays': 7}})

		clients.append(requests)
		return client_class(transport=httpx.MockTransport(respond), trust_env=False)

	monkeypatch.setattr(checkin.httpx, 'Client', factory)
	results = dict(checkin.run_accounts(store.load(), store, concurrency=3, proxy=None))
	assert len(clients) == 5 and all(len(set(requests)) == 1 for requests in clients)
	assert results['good'].success and results['good'].points == 100
	assert all(not results[name].success for name in names[1:])
	assert results['expired'].auth_failed
	assert 'add expired' in results['expired'].message
	assert 'add device' in results['device'].message
	assert 'add blocked' in results['blocked'].message
	assert {a.name: a.status for a in store.load()} == dict.fromkeys(names, 'valid') | {'expired': 'expired'}
	assert 'example-private-cookie' not in capsys.readouterr().out
	assert sum(name == 'network' for name, _ in seen) == 6


@pytest.mark.parametrize(
	'failed,notify_error,notify,expected',
	[
		(False, False, True, 0),
		(True, False, True, 1),
		(False, True, True, 2),
		(True, True, True, 1),
		(False, False, False, 0),
	],
)
def test_main_sends_one_summary_and_preserves_exit_semantics(
	monkeypatch, store, failed, notify_error, notify, expected
):
	for name in ('main', 'backup'):
		store.save(name, f'example-{name}', 'ExampleAgent')
	monkeypatch.setenv('CHECKIN_CONCURRENCY', '2')

	def run(accounts, current_store, **kwargs):
		assert [a.name for a in accounts] == ['main', 'backup']
		assert kwargs['concurrency'] == 2
		return [
			('main', checkin.CheckinResult(True, 'Success', points=100)),
			('backup', checkin.CheckinResult(not failed, 'Done')),
		]

	monkeypatch.setattr(checkin, 'run_accounts', run)
	notifications = []

	def send(content):
		notifications.append(content)
		if notify_error:
			raise RuntimeError('Example failure')

	monkeypatch.setattr(checkin, 'send_feishu', send)
	assert checkin.main(notify=notify) == expected
	assert len(notifications) == int(notify)
	if notify:
		assert 'main' in notifications[0] and 'backup' in notifications[0]
		assert f'结果: {1 if failed else 2}/2' in notifications[0]


def test_cli_selected_account_and_concurrency_override(monkeypatch, store):
	for name in ('main', 'backup'):
		store.save(name, f'example-{name}', 'ExampleAgent')
	monkeypatch.setenv('CHECKIN_CONCURRENCY', '3')

	def run(accounts, current_store, **kwargs):
		assert [a.name for a in accounts] == ['backup']
		assert kwargs['concurrency'] == 1
		return [('backup', checkin.CheckinResult(True, 'Success'))]

	monkeypatch.setattr(checkin, 'run_accounts', run)
	monkeypatch.setattr(checkin, 'send_feishu', lambda *args: pytest.fail('no notification requested'))
	assert checkin.cli(['--account', 'backup', '--concurrency', '1', '--no-notify']) == 0
