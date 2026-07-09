import checkin


class FakeResponse:
	def __init__(self, status_code=200, payload=None):
		self.status_code = status_code
		self._payload = payload or {}

	def json(self):
		return self._payload


class FakeClient:
	def __init__(self, post_payloads=None, get_payloads=None):
		self.post_payloads = post_payloads or []
		self.get_payloads = get_payloads or {}
		self.posts = []
		self.gets = []

	def post(self, url, **kwargs):
		self.posts.append((url, kwargs))
		payload = self.post_payloads.pop(0)
		return FakeResponse(payload=payload)

	def get(self, url, **kwargs):
		self.gets.append((url, kwargs))
		return FakeResponse(payload=self.get_payloads[url])


def test_build_cookie_header_uses_koa_session_cookies():
	header = checkin.build_cookie_header('sess-value', 'sig-value')

	assert header == 'koa:sess=sess-value; koa:sess.sig=sig-value'


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
