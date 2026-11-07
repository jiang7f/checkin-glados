import json

import httpx
import pytest

import checkin


def test_official_challenge_vector_and_observation_delay(monkeypatch):
	events = []
	nonce = '4f97268bc65ac8d8d60d359c4f3881fd'
	def respond(request):
		events.append(request.method)
		if request.method == 'GET':
			return httpx.Response(200, json={'code': 0, 'nonce': nonce, 'ttl': 300000})
		assert json.loads(request.content) == {
			'token': 'glados.cloud', 'nonce': nonce,
			'proof': 'cdc70df2b5f1908c22f22cc617a883debd53981f82d752765bf9f559d6345daf',
		}
		return httpx.Response(200, json={'code': 0})
	monkeypatch.setattr(checkin.time, 'sleep', lambda seconds: events.append(seconds))
	with httpx.Client(transport=httpx.MockTransport(respond)) as client:
		assert checkin.checkin_request(client, {}) == {'code': 0}
	assert events == ['GET', 2.5, 'POST']


@pytest.mark.parametrize('challenge', [
	{'code': -2, 'message': 'Unauthorized'},
	{'code': 0},
	{'code': 0, 'nonce': 'short-lived', 'ttl': 1000},
])
def test_invalid_challenge_never_posts_or_falls_back_to_legacy_token(challenge):
	def respond(request):
		assert request.method == 'GET'
		return httpx.Response(200, json=challenge)
	with httpx.Client(transport=httpx.MockTransport(respond)) as client:
		result = checkin.run_checkin(client, 'test-cookie', max_retries=0)
	assert not result.success


def test_retry_gets_new_challenge_and_does_not_report_reward_as_total_balance(monkeypatch):
	nonces = iter(['first', 'second'])
	posted = []
	def respond(request):
		if request.url == checkin.CHALLENGE_URL:
			return httpx.Response(200, json={'code': 0, 'nonce': next(nonces), 'ttl': 300000})
		if request.method == 'POST':
			posted.append(json.loads(request.content)['nonce'])
			if len(posted) == 1:
				return httpx.Response(200, json={'code': 1, 'message': 'expired challenge'})
			return httpx.Response(200, json={'code': 0, 'points': 10, 'list': [{'balance': '767.0'}]})
		return httpx.Response(503)
	monkeypatch.setattr(checkin.time, 'sleep', lambda seconds: None)
	with httpx.Client(transport=httpx.MockTransport(respond)) as client:
		result = checkin.run_checkin(client, 'test-cookie', max_retries=1)
	assert result.success and result.points == 767
	assert posted == ['first', 'second']
