#!/usr/bin/env python3

import argparse
import base64
import hashlib
import hmac
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import httpx
from dotenv import load_dotenv

from browser_cookie import BrowserSession, CookieImportError, save_session
from accounts import Account, AccountError, AccountStore, validate_name


BASE_URL = 'https://glados.cloud'
CHECKIN_URL = f'{BASE_URL}/api/user/checkin'
POINTS_URL = f'{BASE_URL}/api/user/points'
STATUS_URL = f'{BASE_URL}/api/user/status'
ENV_PATH = Path(__file__).resolve().with_name('.env')
LOGIN_ENV_KEYS = (
	'GLADOS_COOKIE',
	'GLADOS_GLD_SESS',
	'GLADOS_GLD_SESS_SIG',
	'GLADOS_KOA_SESS',
	'GLADOS_KOA_SESS_SIG',
	'GLADOS_USER_AGENT',
)


@dataclass
class CheckinResult:
	success: bool
	message: str
	points: int | None = None
	streak: int | None = None
	days_left: int | None = None
	auth_failed: bool = False


def build_cookie_header(session: str, signature: str, *, cookie_name: str = 'koa:sess') -> str:
	return f'{cookie_name}={session}; {cookie_name}.sig={signature}'


def load_cookie_header() -> str:
	cookie = os.getenv('GLADOS_COOKIE', '').strip()
	if cookie:
		return cookie

	gld_sess = os.getenv('GLADOS_GLD_SESS', '').strip()
	gld_sess_sig = os.getenv('GLADOS_GLD_SESS_SIG', '').strip()
	if gld_sess or gld_sess_sig:
		if not gld_sess or not gld_sess_sig:
			raise ValueError('GLADOS_GLD_SESS and GLADOS_GLD_SESS_SIG must both be configured')
		return build_cookie_header(gld_sess, gld_sess_sig, cookie_name='gld:sess')

	koa_sess = os.getenv('GLADOS_KOA_SESS', '').strip()
	koa_sess_sig = os.getenv('GLADOS_KOA_SESS_SIG', '').strip()
	if koa_sess and koa_sess_sig:
		return build_cookie_header(koa_sess, koa_sess_sig)

	raise ValueError('未配置登录态，请运行 checkin-glados add <名称>。')


def request_headers(cookie_header: str, *, user_agent: str | None = None) -> dict[str, str]:
	return {
		'Accept': 'application/json, text/plain, */*',
		'Content-Type': 'application/json',
		'Cookie': cookie_header,
		'Origin': BASE_URL,
		'Referer': f'{BASE_URL}/console/checkin',
		'User-Agent': user_agent
		or os.getenv('GLADOS_USER_AGENT')
		or 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36',
	}


def parse_json_response(response: httpx.Response) -> dict:
	if response.status_code >= 400:
		return {'code': response.status_code, 'message': f'HTTP {response.status_code}'}
	try:
		payload = response.json()
	except ValueError:
		return {'code': -1, 'message': '网站返回了非 JSON 响应'}
	return payload if isinstance(payload, dict) else {'code': -1, 'message': '网站响应格式无效'}


def to_int(value) -> int | None:
	if value is None:
		return None
	try:
		return int(float(value))
	except (TypeError, ValueError):
		return None


def fetch_points(client, headers: dict[str, str], *, log=print) -> tuple[int | None, int | None]:
	try:
		payload = parse_json_response(client.get(POINTS_URL, headers=headers, timeout=30))
	except Exception as exc:
		log(f'[WARN] 积分查询失败（{type(exc).__name__}）')
		return None, None
	if payload.get('code') != 0:
		return None, None
	points = payload.get('points')
	if points is None:
		history = payload.get('history') or []
		if history and isinstance(history[0], dict):
			points = history[0].get('balance')
	streak = payload.get('streak')
	return to_int(points), to_int(streak)


def fetch_days_left(client, headers: dict[str, str], *, log=print) -> int | None:
	try:
		payload = parse_json_response(client.get(STATUS_URL, headers=headers, timeout=30))
	except Exception as exc:
		log(f'[WARN] 剩余天数查询失败（{type(exc).__name__}）')
		return None
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
			'already checked in',
			'already checked-in',
			"today's observation logged",
			'already signed in today',
			'已签到',
			'重复签到',
		]
	)


def build_success_result(client, headers: dict[str, str], message: str, payload: dict, *, log=print) -> CheckinResult:
	points, streak = fetch_points(client, headers, log=log)
	days_left = fetch_days_left(client, headers, log=log)
	return CheckinResult(
		success=True,
		message=message,
		points=points if points is not None else to_int(payload.get('points')),
		streak=streak if streak is not None else to_int(payload.get('streak')),
		days_left=days_left,
	)


def run_checkin(
	client,
	cookie_header: str,
	*,
	max_retries: int = 5,
	user_agent: str | None = None,
	recovery_hint: str | None = None,
	log=print,
) -> CheckinResult:
	headers = request_headers(cookie_header, user_agent=user_agent)
	max_attempts = max_retries + 1
	last_message = '未知错误'

	for attempt in range(1, max_attempts + 1):
		if attempt > 1:
			log(f'[RETRY] {attempt - 1}/{max_retries}：{last_message}')

		try:
			payload = parse_json_response(
				client.post(CHECKIN_URL, headers=headers, json={'token': 'glados.cloud'}, timeout=30)
			)
		except Exception as exc:
			last_message = f'网络请求失败（{type(exc).__name__}）'
			if attempt < max_attempts:
				continue
			return CheckinResult(success=False, message=last_message)

		code = payload.get('code')
		last_message = str(payload.get('message') or payload.get('msg') or payload.get('error') or f'code={code}')

		if code in (-2, 401, 403):
			return CheckinResult(
				success=False,
				auth_failed=code in (-2, 401),
				message=f'{"登录已过期" if code in (-2, 401) else "访问被拒绝"}（{code}）。'
				+ (recovery_hint or '请运行 checkin-glados login 重新登录。'),
			)

		if code == 4 and payload.get('reason') == 'device-mismatch':
			return CheckinResult(
				False, '登录设备不匹配。' + (recovery_hint or '请运行 checkin-glados login 重新登录。')
			)

		if code == 0 or (code == 1 and is_already_checked_message(last_message)):
			return build_success_result(client, headers, last_message, payload, log=log)

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


def validate_feishu_response(response: httpx.Response) -> None:
	response.raise_for_status()
	try:
		payload = response.json()
	except ValueError:
		raise RuntimeError('飞书响应格式无效') from None
	if not isinstance(payload, dict):
		raise RuntimeError('飞书响应格式无效')
	if not any(key in payload for key in ('StatusCode', 'code', 'errcode')):
		raise RuntimeError('飞书响应缺少状态码')

	if payload.get('StatusCode') not in (None, 0):
		raise RuntimeError(f'飞书错误码 {payload.get("StatusCode")}')
	if payload.get('code') not in (None, 0):
		raise RuntimeError(f'飞书错误码 {payload.get("code")}')
	if payload.get('errcode') not in (None, 0):
		raise RuntimeError(f'飞书错误码 {payload.get("errcode")}')


def send_feishu(content: str) -> None:
	webhook = os.getenv('FEISHU_WEBHOOK', '').strip()
	if not webhook:
		return

	data = {
		'msg_type': 'interactive',
		'card': {
			'elements': [{'tag': 'markdown', 'content': content, 'text_align': 'left'}],
			'header': {'template': 'blue', 'title': {'content': 'GLaDOS Check-in', 'tag': 'plain_text'}},
		},
	}
	secret = os.getenv('FEISHU_SECRET', '').strip()
	if secret:
		timestamp = str(int(time.time()))
		key = f'{timestamp}\n{secret}'.encode()
		data.update(timestamp=timestamp, sign=base64.b64encode(hmac.new(key, b'', hashlib.sha256).digest()).decode())
	try:
		with httpx.Client(timeout=30.0) as client:
			response = client.post(webhook, json=data)
			validate_feishu_response(response)
	except RuntimeError:
		raise
	except Exception as exc:
		# httpx exceptions can contain the full webhook URL. Never print it.
		raise RuntimeError(f'飞书连接失败（{type(exc).__name__}）') from None
	print('[OK] 飞书已发送')


def run_account(account: Account, store: AccountStore, proxy: str | None) -> CheckinResult:
	def log(message):
		print(f'[{account.name}] {message}', flush=True)

	try:
		with store.account_lock(account.name):
			# Re-read after locking so a concurrently replaced or deleted login is never used.
			current = next((item for item in store.load() if item.name == account.name), None)
			if current is None:
				return CheckinResult(False, '账号已被删除，本次跳过。')
			with httpx.Client(http2=True, timeout=30.0, proxy=proxy) as client:
				result = run_checkin(
					client,
					current.cookie_header,
					user_agent=current.user_agent,
					recovery_hint=f'请运行 checkin-glados add {account.name} 重新登录。',
					log=log,
				)
			try:
				if result.success or result.auth_failed:
					store.mark(current, 'valid' if result.success else 'expired')
			except (AccountError, OSError):
				log('[WARN] 状态未保存，请检查文件权限。')
			return result
	except AccountError as exc:
		return CheckinResult(False, str(exc))
	except Exception as exc:
		return CheckinResult(False, f'运行失败（{type(exc).__name__}）')


def run_accounts(
	accounts: list[Account], store: AccountStore, *, concurrency: int, proxy: str | None
) -> list[tuple[str, CheckinResult]]:
	results = {}
	with ThreadPoolExecutor(max_workers=min(concurrency, len(accounts))) as pool:
		futures = {pool.submit(run_account, account, store, proxy): account.name for account in accounts}
		for future in as_completed(futures):
			name = futures[future]
			try:
				results[name] = future.result()
			except Exception as exc:
				results[name] = CheckinResult(False, f'运行失败（{type(exc).__name__}）')
	return [(account.name, results[account.name]) for account in accounts]


def format_account_notification(results: list[tuple[str, CheckinResult]], *, execution_time: str) -> str:
	successes = sum(result.success for _, result in results)
	lines = [
		'GLaDOS签到成功' if successes == len(results) else 'GLaDOS签到存在失败',
		f'时间: {execution_time}',
		f'结果: {successes}/{len(results)}',
	]
	for name, result in results:
		lines.extend(['', f'{"✅" if result.success else "❌"} {name}', f'消息: {result.message}'])
		stats = []
		if result.points is not None:
			stats.append(f'积分: {result.points}')
		if result.streak is not None:
			stats.append(f'连续: {result.streak} 天')
		if result.days_left is not None:
			stats.append(f'剩余: {result.days_left} 天')
		if stats:
			lines.append(' | '.join(stats))
	return '\n'.join(lines)


def format_terminal_results(results: list[tuple[str, CheckinResult]]) -> str:
	lines = []
	for name, result in results:
		if result.success:
			message = '今日已签到' if is_already_checked_message(result.message) else '签到成功'
		else:
			message = ' '.join(result.message.split())
		parts = [f'[{"OK" if result.success else "FAILED"}] {name}：{message}']
		if result.points is not None:
			parts.append(f'积分 {result.points}')
		if result.streak is not None:
			parts.append(f'连续 {result.streak} 天')
		if result.days_left is not None:
			parts.append(f'剩余 {result.days_left} 天')
		lines.append(' · '.join(parts))
	if len(results) > 1:
		lines.append(f'完成：{sum(result.success for _, result in results)}/{len(results)} 个账号成功。')
	return '\n'.join(lines)


def main(*, notify: bool = True, selected: str | None = None, concurrency: int | None = None) -> int:
	load_dotenv(ENV_PATH)
	store = AccountStore(ENV_PATH.parent)
	if store.exists or selected is not None:
		try:
			accounts = store.load()
			if selected is not None:
				validate_name(selected)
				accounts = [account for account in accounts if account.name == selected]
			if not accounts:
				raise AccountError('未找到账号，请运行 checkin-glados add <名称>。')
			workers = concurrency if concurrency is not None else int(os.getenv('CHECKIN_CONCURRENCY', '3'))
			if not 1 <= workers <= 32:
				raise ValueError
		except (AccountError, ValueError) as exc:
			print(f'[FAILED] {exc if isinstance(exc, AccountError) else "CHECKIN_CONCURRENCY 必须为 1–32 的整数。"}')
			return 1
		print('正在签到…', flush=True)
		results = run_accounts(
			accounts, store, concurrency=workers, proxy=os.getenv('CHECKIN_PROXY_URL', '').strip() or None
		)
		content = format_account_notification(results, execution_time=datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
		return report_result(
			content,
			all(result.success for _, result in results),
			notify=notify,
			terminal_content=format_terminal_results(results),
		)

	try:
		cookie_header = load_cookie_header()
		proxy = os.getenv('CHECKIN_PROXY_URL', '').strip() or None
		print('正在签到…', flush=True)
		with httpx.Client(http2=True, timeout=30.0, proxy=proxy) as client:
			result = run_checkin(client, cookie_header)
	except ValueError:
		result = CheckinResult(False, '登录或代理配置无效，请检查 .env 或运行 checkin-glados login。')
	except Exception as exc:
		result = CheckinResult(False, f'运行失败（{type(exc).__name__}）')

	content = format_notification(result, execution_time=datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
	return report_result(
		content, result.success, notify=notify, terminal_content=format_terminal_results([('GLaDOS', result)])
	)


def report_result(content: str, success: bool, *, notify: bool, terminal_content: str) -> int:
	print(terminal_content)
	if notify:
		try:
			send_feishu(content)
		except Exception as exc:
			print(f'[WARN] 飞书通知发送失败：{exc}')
			return 2 if success else 1
	return 0 if success else 1


def validate_session(session: BrowserSession, user_agent: str | None = None) -> bool:
	proxy = os.getenv('CHECKIN_PROXY_URL', '').strip() or None
	with httpx.Client(http2=True, timeout=15.0, proxy=proxy) as client:
		payload = parse_json_response(
			client.get(STATUS_URL, headers=request_headers(session.cookie_header, user_agent=user_agent))
		)
	if payload.get('code') in (-2, 401, 403):
		return False
	if payload.get('code') != 0:
		raise CookieImportError('登录验证失败，请稍后重试或检查网站状态。')
	return True


def login(timeout: int, name: str | None = None) -> int:
	from browser_login import BrowserLoginError, capture_login

	overrides = [key for key in LOGIN_ENV_KEYS if os.getenv(key)]
	load_dotenv(ENV_PATH)
	store = AccountStore(ENV_PATH.parent)
	if name is None and store.exists:
		print('[FAILED] 请指定账号：checkin-glados add <名称>')
		return 1
	try:
		with store.account_lock(name) if name is not None else nullcontext():
			if name is not None:
				store.check_name(name)
			print(f'[INFO] {name or "GLaDOS"}：请在浏览器中登录，完成后自动保存。', flush=True)
			session, user_agent = capture_login(
				store.profile_dir(name) if name is not None else ENV_PATH.parent / '.browser_profiles' / 'glados',
				timeout=timeout,
				proxy=os.getenv('CHECKIN_PROXY_URL', '').strip() or None,
				validate=validate_session,
			)
			if name is not None:
				store.save(name, session.cookie_header, user_agent)
			else:
				save_session(ENV_PATH, session, user_agent=user_agent)
	except (BrowserLoginError, CookieImportError, AccountError) as exc:
		print(f'[FAILED] {exc}')
		return 1
	except KeyboardInterrupt:
		print('[CANCELLED] 已取消登录，未保存。')
		return 130
	except Exception as exc:
		print(f'[FAILED] 登录失败（{type(exc).__name__}），请检查网络或文件权限。')
		return 1
	if name is not None:
		print(f'[OK] {name}：登录已保存。')
	else:
		print('[OK] 登录已保存到 .env。')
		if overrides:
			print(f'[WARN] 环境变量覆盖 .env，请先执行：unset {" ".join(overrides)}')
	return 0


def update_cookie(profile: str | None = None, name: str | None = None) -> int:
	from browser_cookie import read_chrome_session

	overrides = [key for key in LOGIN_ENV_KEYS if os.getenv(key)]
	load_dotenv(ENV_PATH)
	store = AccountStore(ENV_PATH.parent)
	if name is None and store.exists:
		print('[FAILED] 请指定账号：checkin-glados update-cookie <名称>')
		return 1
	try:
		with store.account_lock(name) if name is not None else nullcontext():
			if name is not None:
				store.check_name(name)
			print('[INFO] 读取 Chrome 登录态，可能需要钥匙串授权。', flush=True)
			session = read_chrome_session(profile)
			if not validate_session(session):
				raise CookieImportError(
					f'Chrome 登录态无效，请运行 checkin-glados {"add " + name if name else "login"}。'
				)
			if name is not None:
				store.save(name, session.cookie_header, request_headers(session.cookie_header)['User-Agent'])
			else:
				save_session(ENV_PATH, session)
	except (CookieImportError, AccountError) as exc:
		print(f'[FAILED] {exc}')
		return 1
	except Exception as exc:
		print(f'[FAILED] 导入失败（{type(exc).__name__}），请检查网络或文件权限。')
		return 1
	print(f'[OK] {name}：登录已导入。' if name else '[OK] 登录已导入 .env。')
	if overrides and name is None:
		print(f'[WARN] 环境变量覆盖 .env，请先执行：unset {" ".join(overrides)}')
	return 0


def list_accounts() -> int:
	load_dotenv(ENV_PATH)
	store = AccountStore(ENV_PATH.parent)
	try:
		accounts = store.load()
		if not store.exists:
			try:
				load_cookie_header()
			except ValueError:
				print('尚无账号。请运行 checkin-glados add <名称>。')
			else:
				print('旧版单账号。迁移：checkin-glados migrate <名称>')
			return 0
		if not accounts:
			print('暂无已添加账号。请运行 checkin-glados add <名称>。')
			return 0
		print('账号          最近状态')
		labels = {'valid': '有效', 'expired': '已过期', 'unknown': '未验证'}
		for account in accounts:
			print(f'{account.name:<12}  {labels[account.status]}')
		return 0
	except AccountError as exc:
		print(f'[FAILED] {exc}')
		return 1


def delete_account(name: str) -> int:
	try:
		found = AccountStore(ENV_PATH.parent).delete(name)
	except AccountError as exc:
		print(f'[FAILED] {exc}')
		return 1
	except OSError:
		print('[FAILED] 删除未完成，请检查文件权限。')
		return 1
	print(f'[OK] {name}：已删除本地账号和浏览器数据。' if found else f'[OK] {name}：无账号记录，已清理残留浏览器数据。')
	return 0


def migrate_account(name: str) -> int:
	load_dotenv(ENV_PATH)
	store = AccountStore(ENV_PATH.parent)
	try:
		with store.account_lock(name):
			if any(account.name == name for account in store.load()):
				raise AccountError('账号名称已存在，请换一个名称。')
			cookie = load_cookie_header()
			store.save(name, cookie, request_headers(cookie)['User-Agent'], status='unknown')
	except (AccountError, ValueError) as exc:
		print(f'[FAILED] {exc}')
		return 1
	except OSError:
		print('[FAILED] 迁移失败，请检查文件权限。')
		return 1
	print(f'[OK] 已迁移为 {name}（未验证），原 .env 保留。')
	return 0


def cli(argv: list[str] | None = None) -> int:
	parser = argparse.ArgumentParser(prog='checkin-glados', description='GLaDOS 多账号签到')
	parser.add_argument('--no-notify', action='store_true', help='执行签到但不发送飞书通知')
	parser.add_argument('--account', help='只签到指定名称，默认全部账号')
	parser.add_argument('--concurrency', type=int, help='同时签到的账号数，1–32，默认 CHECKIN_CONCURRENCY 或 3')
	commands = parser.add_subparsers(dest='command')
	add_parser = commands.add_parser('add', help='添加或重新登录账号')
	add_parser.add_argument('name')
	add_parser.add_argument('--timeout', type=int, default=300, help='等待登录的秒数，默认 300')
	commands.add_parser('list', help='查看账号及状态')
	delete_parser = commands.add_parser('delete', help='删除一个本地账号及对应浏览器配置')
	delete_parser.add_argument('name')
	migrate_parser = commands.add_parser('migrate', help='迁移旧版账号')
	migrate_parser.add_argument('name')
	login_parser = commands.add_parser('login', help='打开浏览器登录')
	login_parser.add_argument('name', nargs='?', help='账号名称，指定时等价于 add；省略时兼容旧单账号')
	login_parser.add_argument('--timeout', type=int, default=300, help='等待登录的秒数，默认 300')
	commands.add_parser('notify-test', help='测试飞书通知')
	update = commands.add_parser('update-cookie', help='从 Chrome 导入登录态')
	update.add_argument('name', nargs='?', help='导入的账号名称；省略时兼容旧单账号')
	update.add_argument('--profile', help='Chrome 配置目录名，例如 Default 或 "Profile 1"，默认使用最近使用的配置')
	args = parser.parse_args(argv)
	if args.command and (args.account is not None or args.concurrency is not None or args.no_notify):
		parser.error('--account、--concurrency 和 --no-notify 仅用于执行签到')
	if args.concurrency is not None and not 1 <= args.concurrency <= 32:
		parser.error('--concurrency 必须为 1–32 的整数')
	if getattr(args, 'name', None) is not None:
		try:
			validate_name(args.name)
		except AccountError as exc:
			parser.error(str(exc))
	if args.command in ('login', 'add'):
		if args.timeout <= 0:
			parser.error('--timeout 必须大于 0')
		return login(args.timeout, args.name)
	if args.command == 'list':
		return list_accounts()
	if args.command == 'delete':
		return delete_account(args.name)
	if args.command == 'migrate':
		return migrate_account(args.name)
	if args.command == 'update-cookie':
		return update_cookie(args.profile, args.name)
	if args.command == 'notify-test':
		load_dotenv(ENV_PATH)
		if not os.getenv('FEISHU_WEBHOOK', '').strip():
			print('[FAILED] 请先在 .env 配置 FEISHU_WEBHOOK。')
			return 1
		try:
			send_feishu('GLaDOS 通知配置测试成功。本条消息未执行签到，不代表积分到账。')
		except Exception as exc:
			print(f'[FAILED] {exc}')
			return 1
		return 0
	if args.account is not None or args.concurrency is not None:
		return main(notify=not args.no_notify, selected=args.account, concurrency=args.concurrency)
	return main(notify=False) if args.no_notify else main()


if __name__ == '__main__':
	sys.exit(cli())
