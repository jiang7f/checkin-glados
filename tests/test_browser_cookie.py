import os
from http.cookiejar import Cookie, CookieJar

import httpx
import pytest
from dotenv import dotenv_values

import browser_cookie
import checkin


def make_cookie(name, value, *, domain='.glados.cloud', path='/', expires=None):
	return Cookie(
		version=0,
		name=name,
		value=value,
		port=None,
		port_specified=False,
		domain=domain,
		domain_specified=True,
		domain_initial_dot=domain.startswith('.'),
		path=path,
		path_specified=True,
		secure=True,
		expires=expires,
		discard=False,
		comment=None,
		comment_url=None,
		rest={'HttpOnly': None},
	)


def cookie_jar(*cookies):
	jar = CookieJar()
	for cookie in cookies:
		jar.set_cookie(cookie)
	return jar


def test_extracts_only_complete_glados_session():
	jar = cookie_jar(
		make_cookie('koa:sess', 'new-session'),
		make_cookie('koa:sess.sig', 'new-signature'),
		make_cookie('other', 'irrelevant'),
		make_cookie('koa:sess', 'other-domain', domain='evilglados.cloud'),
		make_cookie('koa:sess', 'other-domain', domain='glados.cloud.evil.test'),
		make_cookie('koa:sess', 'wrong-path', path='/console'),
	)
	assert browser_cookie.session_from_cookies(jar) == browser_cookie.BrowserSession(
		'koa:sess', 'new-session', 'new-signature'
	)


@pytest.mark.parametrize('include_legacy', [False, True])
def test_prefers_new_glados_cookie_names_even_when_old_cookies_remain(include_legacy):
	jar = cookie_jar(make_cookie('gld:sess', 'current-session'), make_cookie('gld:sess.sig', 'current-signature'))
	if include_legacy:
		jar.set_cookie(make_cookie('koa:sess', 'obsolete-session'))
		jar.set_cookie(make_cookie('koa:sess.sig', 'obsolete-signature'))
	session = browser_cookie.session_from_cookies(jar)
	assert session.cookie_header == 'gld:sess=current-session; gld:sess.sig=current-signature'
	assert 'current-session' not in repr(session)


def test_never_mixes_new_session_with_legacy_signature():
	jar = cookie_jar(make_cookie('gld:sess', 'new'), make_cookie('koa:sess.sig', 'old'))
	with pytest.raises(browser_cookie.CookieImportError, match='完整'):
		browser_cookie.session_from_cookies(jar)


@pytest.mark.parametrize(
	'bad_cookie',
	[
		make_cookie('koa:sess.sig', 'expired', expires=1),
		make_cookie('koa:sess.sig', 'other-domain', domain='other.glados.cloud'),
		make_cookie('koa:sess.sig', 'different-path', path='/api'),
		make_cookie('koa:sess.sig', 'bad;cookie'),
	],
)
def test_rejects_incomplete_or_invalid_session(bad_cookie):
	with pytest.raises(browser_cookie.CookieImportError):
		browser_cookie.session_from_cookies(cookie_jar(make_cookie('koa:sess', 'session'), bad_cookie))


def test_rejects_ambiguous_sessions():
	jar = cookie_jar(
		*[
			make_cookie(name, f'{domain}-{name}', domain=domain)
			for domain in ('.glados.cloud', 'glados.cloud')
			for name in ('koa:sess', 'koa:sess.sig')
		]
	)
	with pytest.raises(browser_cookie.CookieImportError, match='多个'):
		browser_cookie.session_from_cookies(jar)


def test_uses_last_used_chrome_profile_and_allows_explicit_override(tmp_path):
	(tmp_path / 'Local State').write_text('{"profile": {"last_used": "Profile 2"}}')
	for relative in ['Profile 2/Network/Cookies', 'Default/Cookies']:
		path = tmp_path / relative
		path.parent.mkdir(parents=True)
		path.touch()
	assert browser_cookie.chrome_cookie_file(user_data_dir=tmp_path) == tmp_path / 'Profile 2/Network/Cookies'
	assert browser_cookie.chrome_cookie_file('Default', user_data_dir=tmp_path) == tmp_path / 'Default/Cookies'
	with pytest.raises(browser_cookie.CookieImportError):
		browser_cookie.chrome_cookie_file('../outside', user_data_dir=tmp_path)


def test_reads_chrome_with_glados_domain_filter(monkeypatch, tmp_path):
	import browser_cookie3

	database = tmp_path / 'Cookies'
	monkeypatch.setattr(browser_cookie, 'chrome_cookie_file', lambda profile: database)

	def load(**kwargs):
		assert kwargs == {'cookie_file': str(database), 'domain_name': 'glados.cloud'}
		return cookie_jar(make_cookie('koa:sess', 'session'), make_cookie('koa:sess.sig', 'signature'))

	monkeypatch.setattr(browser_cookie3, 'chrome', load)
	assert browser_cookie.read_chrome_session() == browser_cookie.BrowserSession('koa:sess', 'session', 'signature')


def test_save_session_preserves_other_settings_and_updates_both_formats(tmp_path):
	path = tmp_path / '.env'
	path.write_text(
		'# local configuration\nFEISHU_WEBHOOK=unchanged\nCHECKIN_PROXY_URL=http://localhost:7890\n'
		"GLADOS_COOKIE='stale'\nGLADOS_KOA_SESS=old\nGLADOS_KOA_SESS_SIG=old-signature\n"
	)
	browser_cookie.save_session(path, browser_cookie.BrowserSession('koa:sess', 'new-session', 'new-signature'))
	values = dotenv_values(path)
	assert values['GLADOS_COOKIE'] == 'koa:sess=new-session; koa:sess.sig=new-signature'
	assert values['GLADOS_KOA_SESS'] == 'new-session'
	assert values['GLADOS_KOA_SESS_SIG'] == 'new-signature'
	assert values['FEISHU_WEBHOOK'] == 'unchanged'
	assert values['CHECKIN_PROXY_URL'] == 'http://localhost:7890'
	assert path.read_text().startswith('# local configuration\n')
	assert path.stat().st_mode & 0o777 == 0o600
	assert list(tmp_path.glob('.env.import-*')) == []


def test_saving_new_session_removes_stale_legacy_settings(tmp_path):
	path = tmp_path / '.env'
	path.write_text('GLADOS_KOA_SESS=old\nGLADOS_KOA_SESS_SIG=old-signature\nFEISHU_WEBHOOK=unchanged\n')
	browser_cookie.save_session(path, browser_cookie.BrowserSession('gld:sess', 'new', 'new-signature'))
	values = dotenv_values(path)
	assert values['GLADOS_COOKIE'] == 'gld:sess=new; gld:sess.sig=new-signature'
	assert values['GLADOS_GLD_SESS'] == 'new'
	assert values['GLADOS_GLD_SESS_SIG'] == 'new-signature'
	assert 'GLADOS_KOA_SESS' not in values
	assert 'GLADOS_KOA_SESS_SIG' not in values
	assert values['FEISHU_WEBHOOK'] == 'unchanged'


def test_failed_write_keeps_original_env_and_removes_temporary_file(monkeypatch, tmp_path):
	path = tmp_path / '.env'
	path.write_text('GLADOS_COOKIE=old\n')

	def fail(*args):
		raise OSError('write failed')

	monkeypatch.setattr(browser_cookie, 'set_key', fail)
	with pytest.raises(OSError):
		browser_cookie.save_session(path, browser_cookie.BrowserSession('koa:sess', 'session', 'signature'))
	assert path.read_text() == 'GLADOS_COOKIE=old\n'
	assert list(tmp_path.glob('.env.import-*')) == []


@pytest.mark.parametrize('mode', ['success', 'rejected', 'http_error', 'invalid_json', 'network_error'])
def test_import_command_validates_before_writing_and_never_notifies(monkeypatch, tmp_path, capsys, mode):
	path = tmp_path / '.env'
	original = 'GLADOS_COOKIE=old\nFEISHU_WEBHOOK=unchanged\n'
	path.write_text(original)
	monkeypatch.setattr(checkin, 'ENV_PATH', path)
	for key in (
		'GLADOS_COOKIE',
		'GLADOS_GLD_SESS',
		'GLADOS_GLD_SESS_SIG',
		'GLADOS_KOA_SESS',
		'GLADOS_KOA_SESS_SIG',
		'CHECKIN_PROXY_URL',
		'FEISHU_WEBHOOK',
	):
		monkeypatch.delenv(key, raising=False)
	# Restore environment variables loaded by dotenv after each case.
	monkeypatch.setattr(os, 'environ', os.environ.copy())
	monkeypatch.setattr(
		browser_cookie,
		'read_chrome_session',
		lambda profile: browser_cookie.BrowserSession('gld:sess', 'private-session', 'private-signature'),
	)
	monkeypatch.setattr(checkin, 'send_feishu', lambda *args: pytest.fail('Import must not send messages'))
	monkeypatch.setattr(checkin, 'run_checkin', lambda *args: pytest.fail('Import must not perform check-in'))
	requests = []

	def respond(request):
		requests.append(request)
		assert request.method == 'GET'
		assert str(request.url) == checkin.STATUS_URL
		assert request.headers['Cookie'] == 'gld:sess=private-session; gld:sess.sig=private-signature'
		if mode == 'network_error':
			raise httpx.ConnectError('sensitive details must not be logged')
		if mode == 'invalid_json':
			return httpx.Response(200, text='<html>login</html>')
		return httpx.Response(401 if mode == 'http_error' else 200, json={'code': 0 if mode == 'success' else -2})

	client_class = httpx.Client
	monkeypatch.setattr(checkin.httpx, 'Client', lambda **kwargs: client_class(transport=httpx.MockTransport(respond)))
	assert checkin.cli(['update-cookie', '--profile', 'Default']) == (0 if mode == 'success' else 1)
	assert len(requests) == 1
	if mode == 'success':
		assert dotenv_values(path)['GLADOS_GLD_SESS'] == 'private-session'
	else:
		assert path.read_text() == original
	output = capsys.readouterr().out
	assert 'private-session' not in output
	assert 'private-signature' not in output
	assert 'sensitive details' not in output


def test_default_command_still_runs_checkin(monkeypatch):
	monkeypatch.setattr(checkin, 'main', lambda: 7)
	assert checkin.cli([]) == 7
