#!/usr/bin/env python3

import os
import sys
from dataclasses import dataclass
from datetime import datetime

import httpx
from dotenv import load_dotenv


BASE_URL = 'https://glados.cloud'
CHECKIN_URL = f'{BASE_URL}/api/user/checkin'
POINTS_URL = f'{BASE_URL}/api/user/points'
STATUS_URL = f'{BASE_URL}/api/user/status'


@dataclass
class CheckinResult:
	success: bool
	message: str
	points: int | None = None
	streak: int | None = None
	days_left: int | None = None


def build_cookie_header(koa_sess: str, koa_sess_sig: str) -> str:
	return f'koa:sess={koa_sess}; koa:sess.sig={koa_sess_sig}'


def load_cookie_header() -> str:
	cookie = os.getenv('GLADOS_COOKIE', '').strip()
	if cookie:
		return cookie

	koa_sess = os.getenv('GLADOS_KOA_SESS', '').strip()
	koa_sess_sig = os.getenv('GLADOS_KOA_SESS_SIG', '').strip()
	if koa_sess and koa_sess_sig:
		return build_cookie_header(koa_sess, koa_sess_sig)

	raise ValueError('GLADOS_COOKIE or GLADOS_KOA_SESS/GLADOS_KOA_SESS_SIG is not configured')


def request_headers(cookie_header: str) -> dict[str, str]:
	return {
		'Accept': 'application/json, text/plain, */*',
		'Content-Type': 'application/json',
		'Cookie': cookie_header,
		'Origin': BASE_URL,
		'Referer': f'{BASE_URL}/console/checkin',
		'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36',
	}


def parse_json_response(response: httpx.Response) -> dict:
	if response.status_code >= 400:
		return {'code': response.status_code, 'message': f'HTTP {response.status_code}'}
	try:
		payload = response.json()
	except ValueError:
		return {'code': -1, 'message': 'Invalid JSON response'}
	return payload if isinstance(payload, dict) else {'code': -1, 'message': 'Invalid response payload'}


def to_int(value) -> int | None:
	if value is None:
		return None
	try:
		return int(float(value))
	except (TypeError, ValueError):
		return None


def fetch_points(client, headers: dict[str, str]) -> tuple[int | None, int | None]:
	payload = parse_json_response(client.get(POINTS_URL, headers=headers, timeout=30))
	if payload.get('code') != 0:
		return None, None
	points = payload.get('points')
	if points is None:
		history = payload.get('history') or []
		if history and isinstance(history[0], dict):
			points = history[0].get('balance')
	streak = payload.get('streak')
	return to_int(points), to_int(streak)


def fetch_days_left(client, headers: dict[str, str]) -> int | None:
	payload = parse_json_response(client.get(STATUS_URL, headers=headers, timeout=30))
	if payload.get('code') != 0:
		return None
	data = payload.get('data') or {}
	days_left = data.get('leftDays') if isinstance(data, dict) else None
	return to_int(days_left)


def is_already_checked_message(message: str) -> bool:
	message_lower = message.lower()
	return any(
		keyword in message_lower
		for keyword in [
			'today',
			'already',
			'return tomorrow',
			'observation logged',
			'已签到',
			'重复签到',
			'明天',
		]
	)


def build_success_result(client, headers: dict[str, str], message: str, payload: dict) -> CheckinResult:
	points, streak = fetch_points(client, headers)
	days_left = fetch_days_left(client, headers)
	return CheckinResult(
		success=True,
		message=message,
		points=points if points is not None else to_int(payload.get('points')),
		streak=streak if streak is not None else to_int(payload.get('streak')),
		days_left=days_left,
	)


def run_checkin(client, cookie_header: str, *, max_retries: int = 5) -> CheckinResult:
	headers = request_headers(cookie_header)
	max_attempts = max_retries + 1
	last_message = 'Unknown error'

	for attempt in range(1, max_attempts + 1):
		if attempt > 1:
			print(f'[RETRY] GLaDOS: retrying check-in ({attempt - 1}/{max_retries})')

		payload = parse_json_response(
			client.post(CHECKIN_URL, headers=headers, json={'token': 'glados.cloud'}, timeout=30)
		)
		code = payload.get('code')
		last_message = str(payload.get('message') or payload.get('msg') or payload.get('error') or f'code={code}')

		if code == 0 or is_already_checked_message(last_message):
			return build_success_result(client, headers, last_message, payload)

		if attempt < max_attempts:
			print(f'[RETRY] GLaDOS: attempt {attempt}/{max_attempts} failed - {last_message}')

	return CheckinResult(success=False, message=last_message)


def format_notification(result: CheckinResult, *, execution_time: str) -> str:
	status_line = '✅ 签到成功' if result.success else '❌ 签到失败'
	lines = [
		'GLaDOS签到成功' if result.success else 'GLaDOS签到失败',
		f'时间: {execution_time}',
		'',
		status_line,
		f'消息: {result.message}',
	]
	if result.points is not None:
		lines.append(f'积分: {result.points}')
	if result.streak is not None:
		lines.append(f'连续: {result.streak} 天')
	if result.days_left is not None:
		lines.append(f'剩余: {result.days_left} 天')
	return '\n'.join(lines)


def send_feishu(content: str) -> None:
	webhook = os.getenv('FEISHU_WEBHOOK', '').strip()
	if not webhook:
		print('[INFO] FEISHU_WEBHOOK not configured, notification skipped')
		return

	data = {
		'msg_type': 'interactive',
		'card': {
			'elements': [{'tag': 'markdown', 'content': content, 'text_align': 'left'}],
			'header': {'template': 'blue', 'title': {'content': 'GLaDOS Check-in', 'tag': 'plain_text'}},
		},
	}
	with httpx.Client(timeout=30.0) as client:
		response = client.post(webhook, json=data)
		response.raise_for_status()
	print('[Feishu]: Message push successful!')


def main() -> int:
	load_dotenv()
	cookie_header = load_cookie_header()
	proxy = os.getenv('CHECKIN_PROXY_URL', '').strip() or None
	client_kwargs: dict = {'http2': True, 'timeout': 30.0}
	if proxy:
		client_kwargs['proxy'] = proxy
		print('[INFO] HTTP client proxy enabled')

	with httpx.Client(**client_kwargs) as client:
		result = run_checkin(client, cookie_header)

	content = format_notification(result, execution_time=datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
	print(content)
	send_feishu(content)
	return 0 if result.success else 1


if __name__ == '__main__':
	try:
		sys.exit(main())
	except Exception as exc:
		print(f'[FAILED] {exc}')
		sys.exit(1)
