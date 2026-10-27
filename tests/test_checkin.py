import pytest

import checkin


class FakeResponse:
	def __init__(self, status_code=200, payload=None):
		self.status_code = status_code
		self._payload = payload or {}

	def json(self):
		return self._payload

	def raise_for_status(self):
		if self.status_code >= 400:
			raise RuntimeError(f'HTTP {self.status_code}')


class FakeClient:
	def __init__(self, post_payloads=None, get_payloads=None):
		self.post_payloads = post_payloads or []
		self.get_payloads = get_payloads or {}
		self.posts = []
		self.gets = []

	def post(self, url, **kwargs):
		self.posts.append((url, kwargs))
		payload = self.post_payloads.pop(0)
		if isinstance(payload, Exception):
			raise payload
		if isinstance(payload, FakeResponse):
			return payload
		return FakeResponse(payload=payload)

	def get(self, url, **kwargs):
		self.gets.append((url, kwargs))
		return FakeResponse(payload=self.get_payloads[url])


def test_build_cookie_header_uses_koa_session_cookies():
	header = checkin.build_cookie_header('sess-value', 'sig-value')

	assert header == 'koa:sess=sess-value; koa:sess.sig=sig-value'


def test_load_cookie_supports_new_glados_session_and_prefers_full_cookie(monkeypatch):
	monkeypatch.delenv('GLADOS_COOKIE', raising=False)
	monkeypatch.setenv('GLADOS_GLD_SESS', 'new-session')
	monkeypatch.setenv('GLADOS_GLD_SESS_SIG', 'new-signature')
	monkeypatch.setenv('GLADOS_KOA_SESS', 'old-session')
	monkeypatch.setenv('GLADOS_KOA_SESS_SIG', 'old-signature')
	assert checkin.load_cookie_header() == 'gld:sess=new-session; gld:sess.sig=new-signature'
	monkeypatch.setenv('GLADOS_COOKIE', 'gld:sess=full; gld:sess.sig=full-signature')
	assert checkin.load_cookie_header() == 'gld:sess=full; gld:sess.sig=full-signature'


def test_partial_new_session_does_not_fall_back_to_stale_legacy_cookie(monkeypatch):
	monkeypatch.delenv('GLADOS_COOKIE', raising=False)
	monkeypatch.setenv('GLADOS_GLD_SESS', 'new-session')
	monkeypatch.delenv('GLADOS_GLD_SESS_SIG', raising=False)
	monkeypatch.setenv('GLADOS_KOA_SESS', 'old-session')
	monkeypatch.setenv('GLADOS_KOA_SESS_SIG', 'old-signature')
	with pytest.raises(ValueError, match='must both be configured'):
		checkin.load_cookie_header()


def test_checkin_posts_token_and_reads_points():
	client = FakeClient(
		post_payloads=[{'code': 0, 'message': 'Checkin success', 'points': 322}],
		get_payloads={
			'https://glados.cloud/api/user/points': {
				'code': 0,
				'points': 322,
				'streak': 3,
				'history': [{'balance': 322}],
			},
			'https://glados.cloud/api/user/status': {
				'code': 0,
				'data': {'leftDays': 324, 'vip': 1},
			},
		},
	)

	result = checkin.run_checkin(client, 'koa:sess=sess; koa:sess.sig=sig')

	assert result.success is True
	assert result.points == 322
	assert result.streak == 3
	assert result.days_left == 324
	assert client.posts[0][0] == 'https://glados.cloud/api/user/checkin'
	assert client.posts[0][1]['json'] == {'token': 'glados.cloud'}
	assert client.posts[0][1]['headers']['Cookie'] == 'koa:sess=sess; koa:sess.sig=sig'


def test_checkin_parses_decimal_point_strings():
	client = FakeClient(
		post_payloads=[{'code': 0, 'message': 'Checkin success', 'points': '325.0000000000000000'}],
		get_payloads={
			'https://glados.cloud/api/user/points': {
				'code': 0,
				'points': '325.0000000000000000',
				'streak': '3',
				'history': [],
			},
			'https://glados.cloud/api/user/status': {
				'code': 0,
				'data': {'leftDays': '324.0000000000000000'},
			},
		},
	)

	result = checkin.run_checkin(client, 'koa:sess=sess; koa:sess.sig=sig')

	assert result.points == 325
	assert result.streak == 3
	assert result.days_left == 324


def test_checkin_retries_failures_until_success():
	client = FakeClient(
		post_payloads=[
			{'code': 1, 'message': 'temporary failure'},
			{'code': 0, 'message': 'Checkin success', 'points': 322},
		],
		get_payloads={
			'https://glados.cloud/api/user/points': {'code': 0, 'points': 322, 'streak': 3, 'history': []},
			'https://glados.cloud/api/user/status': {'code': 0, 'data': {'leftDays': 324}},
		},
	)

	result = checkin.run_checkin(client, 'koa:sess=sess; koa:sess.sig=sig', max_retries=5)

	assert result.success is True
	assert len(client.posts) == 2


def test_checkin_retries_network_exceptions_until_success():
	client = FakeClient(
		post_payloads=[
			OSError('ssl eof'),
			{'code': 0, 'message': 'Checkin success', 'points': 322},
		],
		get_payloads={
			'https://glados.cloud/api/user/points': {'code': 0, 'points': 322, 'streak': 3, 'history': []},
			'https://glados.cloud/api/user/status': {'code': 0, 'data': {'leftDays': 324}},
		},
	)

	result = checkin.run_checkin(client, 'koa:sess=sess; koa:sess.sig=sig', max_retries=5)

	assert result.success is True
	assert len(client.posts) == 2


def test_checkin_treats_already_logged_today_as_success_without_retry():
	client = FakeClient(
		post_payloads=[{'code': 1, 'message': "Today's observation logged. Return tomorrow for more points."}],
		get_payloads={
			'https://glados.cloud/api/user/points': {
				'code': 0,
				'points': '325.0000000000000000',
				'streak': 3,
				'history': [],
			},
			'https://glados.cloud/api/user/status': {
				'code': 0,
				'data': {'leftDays': '324.0000000000000000'},
			},
		},
	)

	result = checkin.run_checkin(client, 'koa:sess=sess; koa:sess.sig=sig', max_retries=5)

	assert result.success is True
	assert result.message == "Today's observation logged. Return tomorrow for more points."
	assert result.points == 325
	assert len(client.posts) == 1


@pytest.mark.parametrize(
	'response',
	[
		FakeResponse(payload={'code': -2, 'message': '没有权限'}),
		FakeResponse(status_code=401),
		FakeResponse(status_code=403),
		FakeResponse(payload={'code': -2, 'message': 'Unauthorized today'}),
	],
)
def test_checkin_stops_on_auth_failure_and_explains_cookie_recovery(response):
	client = FakeClient(post_payloads=[response])

	result = checkin.run_checkin(client, 'koa:sess=private-session; koa:sess.sig=private-signature')

	assert result.success is False
	assert len(client.posts) == 1
	assert client.gets == []
	assert 'checkin-glados login' in result.message
	assert 'private-session' not in result.message
	assert 'private-signature' not in result.message


def test_format_notification_uses_final_result_only():
	result = checkin.CheckinResult(
		success=True,
		message='Checkin success',
		points=322,
		streak=3,
		days_left=324,
	)

	content = checkin.format_notification(result, execution_time='2026-07-08 18:00:00')

	assert content.splitlines()[0] == 'GLaDOS签到成功'
	assert '✅ 签到成功' in content
	assert '积分: 322' in content
	assert '连续: 3 天' in content
	assert '剩余: 324 天' in content


def test_validate_feishu_response_rejects_business_error():
	response = FakeResponse(payload={'StatusCode': 999, 'StatusMessage': 'bad webhook'})

	try:
		checkin.validate_feishu_response(response)
	except RuntimeError as exc:
		assert '999' in str(exc)
	else:
		raise AssertionError('expected RuntimeError')
