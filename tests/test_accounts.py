import json
import stat
from concurrent.futures import ThreadPoolExecutor

import pytest

import accounts
from accounts import AccountError, AccountStore, validate_name


@pytest.mark.parametrize('name', ['', '../main', '/tmp/main', '.hidden', 'a/b', 'a b', 'a\n', 'a' * 49])
def test_names_cannot_escape_private_storage(name):
	with pytest.raises(AccountError):
		validate_name(name)


def test_private_storage_roundtrip_and_redacted_repr(tmp_path):
	store = AccountStore(tmp_path)
	store.save('main', 'example-private-cookie', 'ExampleAgent')
	(account,) = store.load()
	assert account.cookie_header == 'example-private-cookie'
	assert account.user_agent == 'ExampleAgent'
	assert account.status == 'valid' and account.verified_at
	assert 'example-private-cookie' not in repr(account)
	assert stat.S_IMODE(store.root.stat().st_mode) == 0o700
	assert stat.S_IMODE(store.path.stat().st_mode) == 0o600


def test_concurrent_saves_do_not_lose_other_accounts(tmp_path):
	store = AccountStore(tmp_path)
	with ThreadPoolExecutor(max_workers=6) as pool:
		list(pool.map(lambda n: store.save(f'account{n}', f'example-cookie-{n}', f'ExampleAgent{n}'), range(12)))
	assert {a.name for a in store.load()} == {f'account{n}' for n in range(12)}


def test_atomic_write_failure_keeps_original(tmp_path, monkeypatch):
	store = AccountStore(tmp_path)
	store.save('main', 'example-original', 'ExampleAgent')
	original = store.path.read_bytes()

	def fail(*args):
		raise OSError('simulated disk error')

	monkeypatch.setattr(accounts.os, 'replace', fail)
	with pytest.raises(OSError):
		store.save('main', 'example-replacement', 'ExampleAgent')
	assert store.path.read_bytes() == original
	assert not list(store.root.glob('.accounts-*'))


def test_corrupt_registry_is_not_overwritten_or_exposed(tmp_path):
	store = AccountStore(tmp_path)
	store.root.mkdir()
	original = '{"example-private-cookie": INVALID}'
	store.path.write_text(original)
	with pytest.raises(AccountError) as exc:
		store.save('main', 'example-new', 'ExampleAgent')
	assert store.path.read_text() == original
	assert 'example-private-cookie' not in str(exc.value)


def test_delete_preserves_other_accounts_profiles_and_empty_registry(tmp_path):
	store = AccountStore(tmp_path)
	for name in ('main', 'backup'):
		store.save(name, f'example-{name}', 'ExampleAgent')
		store.profile_dir(name).mkdir(parents=True)
		(store.profile_dir(name) / 'session').write_text('example')
	assert store.delete('main')
	assert [a.name for a in store.load()] == ['backup']
	assert not store.profile_dir('main').exists()
	assert (store.profile_dir('backup') / 'session').exists()
	assert store.delete('backup')
	assert store.exists and store.load() == []


def test_mark_cannot_overwrite_a_replaced_or_deleted_session(tmp_path):
	store = AccountStore(tmp_path)
	store.save('main', 'example-old', 'ExampleAgent')
	old = store.load()[0]
	store.save('main', 'example-new', 'ExampleAgent')
	store.mark(old, 'expired')
	assert store.load()[0].status == 'valid'
	store.delete('main')
	store.mark(old, 'expired')
	assert store.load() == []


def test_busy_account_is_rejected_but_other_accounts_can_save(tmp_path):
	store = AccountStore(tmp_path)
	with store.account_lock('registry'):
		# Account names must not collide with the registry lock filename.
		store.save('registry', 'example-cookie', 'ExampleAgent')
		with pytest.raises(AccountError, match='正在'):
			with store.account_lock('REGISTRY'):
				pytest.fail('same-account operation acquired a second lock')
		store.save('backup', 'example-cookie', 'ExampleAgent')


def test_case_collisions_are_rejected(tmp_path):
	store = AccountStore(tmp_path)
	store.save('Main', 'example-original', 'ExampleAgent')
	for action in (
		lambda: store.save('main', 'example-new', 'ExampleAgent'),
		lambda: store.delete('main'),
		lambda: store.check_name('main'),
	):
		with pytest.raises(AccountError):
			action()
	assert store.load()[0].cookie_header == 'example-original'


@pytest.mark.parametrize('target', ['registry', 'root', 'profile'])
def test_symlinks_cannot_redirect_credentials_or_profile_deletion(tmp_path, target):
	store = AccountStore(tmp_path)
	outside = tmp_path / 'outside'
	outside.mkdir()
	(outside / 'keep').write_text('example-private')
	if target == 'root':
		store.root.symlink_to(outside, target_is_directory=True)
	elif target == 'registry':
		store.root.mkdir()
		store.path.symlink_to(outside / 'keep')
	else:
		store.save('main', 'example-cookie', 'ExampleAgent')
		store.profiles.mkdir(parents=True)
		store.profile_dir('main').symlink_to(outside, target_is_directory=True)
	with pytest.raises(AccountError):
		if target == 'profile':
			store.delete('main')
		else:
			store.save('main', 'example-cookie', 'ExampleAgent')
	assert (outside / 'keep').read_text() == 'example-private'


def test_invalid_record_metadata_is_rejected(tmp_path):
	store = AccountStore(tmp_path)
	store.save('main', 'example-cookie', 'ExampleAgent')
	data = json.loads(store.path.read_text())
	data['accounts']['main']['checked_at'] = {'example-private': 1}
	store.path.write_text(json.dumps(data))
	with pytest.raises(AccountError):
		store.load()
