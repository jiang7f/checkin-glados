import base64
import hashlib
import hmac

import httpx
import pytest

import checkin


def test_feishu_signed_payload(monkeypatch):
	monkeypatch.setenv('FEISHU_WEBHOOK', 'https://open.feishu.cn/open-apis/bot/v2/hook/example')
	monkeypatch.setenv('FEISHU_SECRET', 'example-secret')
	monkeypatch.setattr(checkin.time, 'time', lambda: 1700000000)
	requests = []

	def respond(request):
		import json

		requests.append(json.loads(request.content))
		return httpx.Response(200, json={'code': 0})

	client = httpx.Client
	monkeypatch.setattr(checkin.httpx, 'Client', lambda **kw: client(transport=httpx.MockTransport(respond)))
	checkin.send_feishu('GLaDOS test')
	assert requests[0]['timestamp'] == '1700000000'
	expected = base64.b64encode(hmac.new(b'1700000000\nexample-secret', b'', hashlib.sha256).digest()).decode()
	assert requests[0]['sign'] == expected


@pytest.mark.parametrize('payload', [{}, [], {'code': 19021}, {'StatusCode': 1}, {'errcode': 5}])
def test_feishu_does_not_report_malformed_or_rejected_messages_as_delivered(payload):
	response = httpx.Response(200, json=payload, request=httpx.Request('POST', 'https://example.test'))
	with pytest.raises(RuntimeError):
		checkin.validate_feishu_response(response)


def test_notification_failure_preserves_successful_checkin_and_does_not_retry(monkeypatch, capsys):
	monkeypatch.setattr(checkin, 'load_dotenv', lambda *args: None)
	monkeypatch.setattr(checkin, 'load_cookie_header', lambda: 'fake-cookie')
	monkeypatch.setattr(
		checkin, 'run_checkin', lambda *args: checkin.CheckinResult(True, 'Checkin success', points=100)
	)
	calls = []

	def fail(content):
		calls.append(content)
		raise RuntimeError('Feishu request failed: 19021')

	monkeypatch.setattr(checkin, 'send_feishu', fail)
	assert checkin.main() == 2
	assert len(calls) == 1
	assert calls[0].startswith('GLaDOS签到成功')
	assert '通知发送失败' in capsys.readouterr().out


def test_no_notify_flag(monkeypatch):
	monkeypatch.setattr(checkin, 'main', lambda *, notify: 0 if not notify else 9)
	assert checkin.cli(['--no-notify']) == 0


@pytest.mark.parametrize('message', ['Try again today', 'Already unauthorized', '明天再试，服务异常'])
def test_failure_with_today_or_already_is_not_a_success(message):
	class Client:
		def post(self, *args, **kwargs):
			return httpx.Response(200, json={'code': 1, 'message': message})

	result = checkin.run_checkin(Client(), 'test-cookie', max_retries=0)
	assert result.success is False
