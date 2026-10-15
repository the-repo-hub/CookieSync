"""Проверки протокола, конкуренции и CLI с временными аккаунтами и TLS-ключами."""
import asyncio
import json
import logging
import os
import subprocess
import threading
import time
from unittest.mock import patch

import pytest
import pytest_asyncio
from websockets.asyncio.connection import Connection

from cookieserver.manage import RunServerCommand, build_parser
from cookieserver.src.choices import Commands, Fields
from cookieserver.src.commands import RegisterCookiesCommand, SetCookiesCommand
from cookieserver.src.request import Request
from cookieserver.src.server import Server
from cookieserver.src.settings import (
    ACCOUNTS_PATH,
    COOKIE_SERVER_PATH,
    COOKIE_UPDATE_INTERVAL,
    KEYS_PATH,
)
from cookieserver.src.storage import Account, AccountStorage, run_storage_write
from cookieserver.tests.AsyncWSClient import AsyncWSClient

HOST = '127.0.0.1'


@pytest.fixture(scope='session', autouse=True)
def asset_dirs(tmp_path_factory):
    """Тестовые сертификаты не должны создавать или заменять рабочие TLS-ключи."""
    keys_path = tmp_path_factory.mktemp('tls_keys')
    cert_path = str(keys_path / 'cert.pem')
    key_path = str(keys_path / 'key.pem')
    subprocess.run(
        [
            'openssl', 'req', '-newkey', 'rsa:2048', '-nodes',
            '-keyout', key_path, '-x509', '-days', '1',
            '-out', cert_path, '-subj', '/CN=localhost',
        ],
        check=True,
        capture_output=True,
    )
    with pytest.MonkeyPatch.context() as mpatch:
        mpatch.setattr('cookieserver.src.server.CERT_PATH', cert_path)
        mpatch.setattr('cookieserver.src.server.KEY_PATH', key_path)
        mpatch.setattr('cookieserver.manage.CERT_PATH', cert_path)
        mpatch.setattr('cookieserver.manage.KEY_PATH', key_path)
        mpatch.setattr('cookieserver.tests.test_cookieserver.KEYS_PATH', str(keys_path))
        yield


@pytest.fixture(autouse=True)
def temp_accounts_storage(tmp_path, monkeypatch):
    """Изолирует тесты от реальной папки cookieserver/accounts/.

    Иначе серверные/менеджмент-тесты пишут account-файлы прямо в рабочее
    хранилище (например, custom_cert_account.json, post_tls_account.json).
    """
    accounts_dir = tmp_path / 'server_accounts'
    accounts_dir.mkdir()
    monkeypatch.setattr('cookieserver.src.storage.ACCOUNTS_PATH', str(accounts_dir))
    monkeypatch.setattr('cookieserver.tests.test_cookieserver.ACCOUNTS_PATH', str(accounts_dir))
    return accounts_dir


@pytest.fixture
def cookies_not_sample():
    """Куки, которых точно нет на сервере"""
    with open(os.path.join(COOKIE_SERVER_PATH, "tests/test_cookie.json")) as f:
        cookies = json.loads(f.read())
    cookies[0]['value'] = "value_not_sample"
    yield cookies


@pytest_asyncio.fixture
async def server():
    """Предоставляет TLS-сервер на свободном порту и останавливает его после теста."""
    server = Server(host=HOST, port=0)
    await server.start()
    try:
        yield server
    finally:
        await server.stop()


@pytest.fixture
def server_url(server):
    """Возвращает wss:// URL фактически выделенного серверу порта."""
    sock = server.server.sockets[0]
    port = sock.getsockname()[1]
    return f'wss://{HOST}:{port}'


@pytest_asyncio.fixture
async def plain_server():
    """Предоставляет сервер без TLS на свободном порту с гарантированной остановкой."""
    server = Server(host=HOST, port=0, use_tls=False)
    await server.start()
    try:
        yield server
    finally:
        await server.stop()


@pytest_asyncio.fixture
async def async_client(server_url):
    """Подключает основной тестовый клиент к TLS-серверу на время теста."""
    client = AsyncWSClient('async_client')
    await client.connect(server_url)
    yield client
    await client.close()


@pytest_asyncio.fixture
async def second_client(server_url):
    """Предоставляет независимый сокет для проверки рассылки и конкуренции."""
    client = AsyncWSClient('second_client')
    await client.connect(server_url)
    yield client
    await client.close()


@pytest_asyncio.fixture
async def third_client(server_url):
    """Предоставляет третий сокет для проверки рассылки нескольким получателям."""
    client = AsyncWSClient('third_client')
    await client.connect(server_url)
    yield client
    await client.close()


@pytest.fixture
def cookies_other():
    """Возвращает альтернативную полную пару для проверки смены значения cookies."""
    with open(os.path.join(COOKIE_SERVER_PATH, "tests/test_cookie.json")) as f:
        cookies = json.loads(f.read())
    cookies[0]['value'] = "value_other"
    yield cookies


@pytest.fixture
def not_storage_account():
    """Имя отсутствующего аккаунта для проверки автоматического создания."""
    return 'test_to_create'


@pytest.fixture
def other_account():
    """Имя второго аккаунта для проверки изоляции и повторной регистрации."""
    return 'other_account'


@pytest.fixture
def account():
    """Имя основного аккаунта теста в изолированном хранилище."""
    return 'test_account'


def register_payload(account):
    """Создаёт запрос register без uuid, который добавляет AsyncWSClient."""
    return {
        Fields.command: Commands.register,
        Fields.account: account,
    }


def set_payload(account, cookies):
    """Создаёт запрос set с вложенной парой cookies; uuid добавляет AsyncWSClient."""
    return {
        Fields.command: Commands.set,
        Fields.account: account,
        Fields.payload: cookies,
    }


@pytest_asyncio.fixture
async def runtime_expired_account(server, account, async_client, cookies_not_sample, monkeypatch) -> Account:
    """Сохраняет пару и переводит часы к истечению одной половины без рестарта."""
    await async_client.send_request(register_payload(account))
    expiry = time.time() + 60
    cookies = [dict(cookie) for cookie in cookies_not_sample]
    cookies[0]['expirationDate'] = expiry
    response = await async_client.send_request(set_payload(account, cookies))
    assert response[Fields.accepted] is True
    monkeypatch.setattr('cookieserver.src.storage.time.time', lambda: expiry)
    account_obj = server.storage.require_account(account)
    assert account_obj.retry_after() > 0
    return account_obj


class TestRuntimeExpiry:
    """Истечение cookies на работающем сервере без повторного использования ревизий."""

    @pytest.mark.asyncio
    async def test_registration_cleans_expired_pair_and_preserves_revision(
        self, runtime_expired_account, second_client,
    ):
        account: Account = runtime_expired_account
        revision = account.revision
        response = await second_client.send_request(register_payload(account.name))
        assert response[Fields.result] is True
        assert response[Fields.uuid] == second_client.last_request_uuid
        assert response[Fields.payload] == []
        assert response[Fields.revision] == revision
        assert response[Fields.retry_after] == 0
        with open(account.full_path) as file:
            assert json.load(file) == {'payload': [], 'updated_at': 0.0, 'revision': revision}

    @pytest.mark.asyncio
    @pytest.mark.parametrize('command', [Commands.set, Commands.refresh])
    async def test_fresh_pair_replaces_expired_pair_during_old_cooldown(
        self, runtime_expired_account, async_client, cookies_other, command,
    ):
        account: Account = runtime_expired_account
        revision = account.revision
        request = {**set_payload(account.name, cookies_other), Fields.command: command}
        if command == Commands.refresh:
            request[Fields.expected_revision] = revision
        response = await async_client.send_request(request)
        assert response[Fields.accepted] is True
        assert response[Fields.revision] == revision + 1
        assert response[Fields.payload] == cookies_other
        assert response[Fields.uuid] == async_client.last_request_uuid
        assert AccountStorage().require_account(account.name).revision == revision + 1

    @pytest.mark.asyncio
    async def test_stale_refresh_returns_cleaned_pair_without_rebasing(
        self, runtime_expired_account, async_client, cookies_other,
    ):
        account: Account = runtime_expired_account
        revision = account.revision
        response = await async_client.send_request({
            **set_payload(account.name, cookies_other), Fields.command: Commands.refresh,
            Fields.expected_revision: revision - 1,
        })
        assert response[Fields.accepted] is False
        assert response[Fields.payload] == []
        assert response[Fields.revision] == revision
        assert response[Fields.retry_after] == 0

    @pytest.mark.asyncio
    async def test_failed_cleanup_rolls_back_and_registration_can_retry(
        self, runtime_expired_account, second_client, server,
    ):
        account: Account = runtime_expired_account
        previous = account.payload, account.updated_at, account._locked_until, account.revision
        with patch.object(account, 'write_file', side_effect=OSError('disk full')):
            response = await second_client.send_request(register_payload(account.name))
        assert response[Fields.result] is False
        assert response[Fields.uuid] == second_client.last_request_uuid
        assert (account.payload, account.updated_at, account._locked_until, account.revision) == previous
        assert len(server.storage.websockets_by_account[account.name]) == 1
        response = await second_client.send_request(register_payload(account.name))
        assert response[Fields.result] is True
        assert response[Fields.payload] == []
        assert response[Fields.revision] == previous[-1]

    @pytest.mark.asyncio
    async def test_cancelled_cleanup_finishes_under_lock_and_does_not_block_other_accounts(
        self, runtime_expired_account, server, second_client,
    ):
        account: Account = runtime_expired_account
        websocket = next(iter(server.storage.websockets_by_account[account.name]))
        started = asyncio.Event()
        release = threading.Event()
        loop = asyncio.get_running_loop()
        original_write = account.write_file

        def delayed_write():
            loop.call_soon_threadsafe(started.set)
            if not release.wait(timeout=5):
                raise TimeoutError('Cleanup worker was not released')
            original_write()

        with patch.object(account, 'write_file', side_effect=delayed_write):
            request = Request({**register_payload(account.name), Fields.uuid: 'cleanup'})
            cleaning = asyncio.create_task(RegisterCookiesCommand().execute(server.storage, request, websocket))
            try:
                await asyncio.wait_for(started.wait(), 3)
                response = await second_client.send_request(register_payload('other_during_cleanup'))
                assert response[Fields.result] is True
                for _ in range(3):
                    cleaning.cancel()
                    turn = loop.create_future()
                    loop.call_soon(turn.set_result, None)
                    await turn
                    assert account.lock.locked()
                    assert not cleaning.done()
            finally:
                release.set()
                with pytest.raises(asyncio.CancelledError):
                    await cleaning
        assert not account.lock.locked()
        assert account.payload == []
        restored = AccountStorage().require_account(account.name)
        assert restored.payload == []
        assert restored.revision == account.revision == 1


class TestCookieServer:
    """Регистрация, рассылка, cooldown, ошибки протокола и жизненный цикл сокетов."""

    async def wait_until(self, predicate, timeout=1, interval=0.01):
        """Неблокирующе ждёт синхронный predicate; timeout и interval — в секундах."""
        start = asyncio.get_running_loop().time()
        while True:
            if predicate():
                return
            if asyncio.get_running_loop().time() - start > timeout:
                raise TimeoutError("Condition not met")
            await asyncio.sleep(interval)

    @pytest.mark.asyncio
    async def test_broadcast_timeout_does_not_wait_for_slow_peer_close(
        self, server, account, async_client, second_client, cookies_not_sample, monkeypatch,
    ):
        await async_client.send_request(register_payload(account))
        await second_client.send_request(register_payload(account))
        monkeypatch.setattr('cookieserver.src.commands.BROADCAST_TIMEOUT', 0.01)
        release_close = asyncio.Event()
        send_cancelled = asyncio.Event()
        aborted = asyncio.Event()

        class SlowPeer:
            """Получатель с зависшей отправкой и независимо управляемым close."""

            remote_address = ('slow-test-peer', 1)
            close_called = False

            def __init__(self):
                self.transport = self

            async def send(self, message):
                try:
                    await asyncio.Future()
                finally:
                    send_cancelled.set()

            async def close(self, **kwargs):
                self.close_called = True
                await release_close.wait()

            def abort(self):
                aborted.set()

        peer = SlowPeer()
        server.storage.add_client(peer, account)
        try:
            response = await async_client.send_request(set_payload(account, cookies_not_sample), timeout=1)
            assert response[Fields.result] is True
            assert response[Fields.accepted] is True
            assert response[Fields.uuid] == async_client.last_request_uuid
            assert send_cancelled.is_set()
            assert aborted.is_set()
            assert not peer.close_called
            assert not server.storage.require_account(account).lock.locked()
            push = await second_client.recv_server_message()
            assert push[Fields.command] == Commands.set
            assert Fields.uuid not in push
            assert push[Fields.payload] == cookies_not_sample
            following = await second_client.send_request(register_payload(account), timeout=1)
            assert following[Fields.revision] == response[Fields.revision]
        finally:
            release_close.set()
            server.storage.remove_client(peer)

    @pytest.mark.asyncio
    async def test_failed_broadcast_aborts_real_connection_and_cleans_registration(
        self, server, account, async_client, second_client, cookies_not_sample,
    ):
        await async_client.send_request(register_payload(account))
        await second_client.send_request(register_payload(account))
        peer: Connection = next(ws for ws in server.storage.websockets_by_account[account]
                                if ws.remote_address == second_client.ws.local_address)

        async def failed_send(message):
            raise OSError('simulated transport failure')

        with patch.object(peer, 'send', new=failed_send):
            response = await async_client.send_request(set_payload(account, cookies_not_sample))
        assert response[Fields.accepted] is True
        await asyncio.wait_for(peer.wait_closed(), timeout=1)
        await self.wait_until(lambda: peer not in server.storage._ws_accounts)
        assert peer not in server.storage.websockets_by_account[account]
        assert len(server.storage.websockets_by_account[account]) == 1

    @pytest.mark.asyncio
    async def test_register(self, server, account, async_client):
        response = await async_client.send_request(register_payload(account))
        assert response[Fields.result] is True
        assert response[Fields.uuid] == async_client.last_request_uuid
        assert server.storage.websockets_by_account.get(account)
        assert response[Fields.payload] == server.storage.get_account(account).payload

        # закрываем соединение, в это время сервер должен выкинуть клиента из списка
        await async_client.close()
        await self.wait_until(lambda: not server.storage.websockets_by_account.get(account))

    @pytest.mark.asyncio
    async def test_disconnect_log_keeps_client_address(
        self, server, account, async_client, caplog,
    ):
        await async_client.send_request(register_payload(account))
        client_address = async_client.ws.local_address

        with caplog.at_level(logging.INFO, logger='cookieserver.src.server'):
            await async_client.close()
            await self.wait_until(
                lambda: not server.storage.websockets_by_account.get(account)
            )

        disconnect_messages = [
            record.getMessage() for record in caplog.records
            if record.name == 'cookieserver.src.server'
            and record.getMessage().startswith('Client disconnected:')
        ]
        assert disconnect_messages
        assert any(str(client_address) in message for message in disconnect_messages)
        assert all(not message.endswith('None') for message in disconnect_messages)

    @pytest.mark.asyncio
    async def test_client_disconnect_removes_only_own_connection(
        self, server, account, async_client, second_client,
    ):
        """Отключение одного клиента не должно отключать остальных клиентов аккаунта."""
        await async_client.send_request(register_payload(account))
        await second_client.send_request(register_payload(account))
        assert len(server.storage.websockets_by_account.get(account)) == 2
        assert len(server.storage._ws_accounts) == 2

        await async_client.close()
        await self.wait_until(
            lambda: len(server.storage.websockets_by_account.get(account, set())) == 1
        )

        # второй клиент остался в аккаунте, обратный индекс тоже почищен
        assert len(server.storage.websockets_by_account.get(account)) == 1
        assert len(server.storage._ws_accounts) == 1

        # оставшийся клиент по-прежнему работает
        response = await second_client.send_request(register_payload(account))
        assert response[Fields.result] is True

    @pytest.mark.asyncio
    async def test_client_disconnect_of_unregistered_socket(
        self, server, account, async_client,
    ):
        """Отключение сокета без регистрации не должно кидать ошибок."""
        await async_client.close()
        await self.wait_until(lambda: not server.storage.websockets_by_account.items())
        assert not server.storage._ws_accounts

    @pytest.mark.asyncio
    async def test_register_creates_account(self, server, async_client, not_storage_account):
        assert server.storage.get_account(not_storage_account) is None
        response = await async_client.send_request(register_payload(not_storage_account))
        assert response[Fields.result] is True
        assert response[Fields.uuid] == async_client.last_request_uuid
        assert response[Fields.payload] == []
        assert response[Fields.revision] == 0
        assert response[Fields.retry_after] == 0
        assert len(server.storage.websockets_by_account[not_storage_account]) == 1
        persisted = AccountStorage().require_account(not_storage_account)
        assert persisted.payload == []
        assert persisted.revision == 0

    @pytest.mark.asyncio
    async def test_concurrent_registration_creates_one_account(
        self, server, account, async_client, second_client, cookies_not_sample,
    ):
        with patch.object(Account, 'write_file', autospec=True, side_effect=Account.write_file) as write:
            first, second = await asyncio.gather(
                async_client.send_request(register_payload(account)),
                second_client.send_request(register_payload(account)),
            )
        assert first[Fields.result] is second[Fields.result] is True
        assert first[Fields.uuid] == async_client.last_request_uuid
        assert second[Fields.uuid] == second_client.last_request_uuid
        assert first[Fields.payload] == second[Fields.payload] == []
        assert write.call_count == 1
        assert server.storage.get_all_accounts() == [account]
        assert len(server.storage.websockets_by_account[account]) == 2

        response = await async_client.send_request(set_payload(account, cookies_not_sample))
        assert response[Fields.accepted] is True
        push = await second_client.recv_server_message()
        assert push[Fields.payload] == cookies_not_sample
        assert Fields.uuid not in push

    @pytest.mark.asyncio
    @pytest.mark.parametrize('name', [
        None, '', '   ', 123, ['office'], {'name': 'office'},
        '../outside', '..', '/absolute', r'..\outside', 'a/b', r'a\b',
        'a:b', 'name\x00', 'name\n', 'name.', 'a' * 65, 'CON', 'nul', 'COM1', 'LPT¹',
    ])
    async def test_register_rejects_invalid_account_name(
        self, server, async_client, name, temp_accounts_storage,
    ):
        response = await async_client.send_request(register_payload(name))
        assert response[Fields.result] is False
        assert response[Fields.uuid] == async_client.last_request_uuid
        assert 'account' in response[Fields.message].lower()
        assert server.storage.get_all_accounts() == []
        assert not server.storage.websockets_by_account
        assert list(temp_accounts_storage.iterdir()) == []
        # A validation error must not close the connection.
        valid = await async_client.send_request(register_payload('office_team'))
        assert valid[Fields.result] is True

    @pytest.mark.asyncio
    async def test_register_creates_missing_directory(
        self, server, async_client, tmp_path, monkeypatch,
    ):
        missing = tmp_path / 'new' / 'accounts'
        monkeypatch.setattr('cookieserver.src.storage.ACCOUNTS_PATH', str(missing))
        response = await async_client.send_request(register_payload('Офис_1'))
        assert response[Fields.result] is True
        assert (missing / 'Офис_1.json').is_file()

    @pytest.mark.asyncio
    async def test_failed_account_creation_can_be_retried(
        self, server, async_client, account, temp_accounts_storage,
    ):
        with patch.object(Account, 'write_file', side_effect=OSError('private disk error')):
            response = await async_client.send_request(register_payload(account))
        assert response[Fields.result] is False
        assert response[Fields.uuid] == async_client.last_request_uuid
        assert response[Fields.message] == 'Internal server error'
        assert server.storage.get_account(account) is None
        assert not server.storage.websockets_by_account
        assert list(temp_accounts_storage.iterdir()) == []

        retry = await async_client.send_request(register_payload(account))
        assert retry[Fields.result] is True
        assert AccountStorage().get_account(account) is not None

    @pytest.mark.asyncio
    async def test_register_preserves_existing_file_after_restart(
        self, server, async_client, account, cookies_not_sample, temp_accounts_storage,
    ):
        await async_client.send_request(register_payload(account))
        update = await async_client.send_request(set_payload(account, cookies_not_sample))
        account_file = temp_accounts_storage / f'{account}.json'
        before = account_file.read_bytes()
        await async_client.close()
        await server.stop()

        restarted = Server(HOST, 0, use_tls=False)
        await restarted.start()
        try:
            port = restarted.server.sockets[0].getsockname()[1]
            await async_client.connect(f'ws://{HOST}:{port}')
            response = await async_client.send_request(register_payload(account))
            assert response[Fields.result] is True
            assert response[Fields.uuid] == async_client.last_request_uuid
            assert response[Fields.payload] == cookies_not_sample
            assert response[Fields.revision] == update[Fields.revision]
            assert response[Fields.retry_after] > 0
            assert account_file.read_bytes() == before
        finally:
            await async_client.close()
            await restarted.stop()

    @pytest.mark.asyncio
    async def test_register_does_not_overwrite_unreadable_account(
        self, server, async_client, temp_accounts_storage,
    ):
        path = temp_accounts_storage / 'corrupt.json'
        path.write_text('{broken json')
        response = await async_client.send_request(register_payload('corrupt'))
        assert response[Fields.result] is False
        assert response[Fields.uuid] == async_client.last_request_uuid
        assert path.read_text() == '{broken json'
        assert server.storage.get_account('corrupt') is None
        assert not server.storage.websockets_by_account

    @pytest.mark.asyncio
    @pytest.mark.parametrize('cancel_count', [1, 3])
    async def test_cancelled_creation_finishes_before_retry(self, server, monkeypatch, cancel_count):
        account_storage: AccountStorage = server.storage
        started = asyncio.Event()
        release = threading.Event()
        loop = asyncio.get_running_loop()
        persist = account_storage._persist_new_account
        writes = []

        def delayed_write(account_obj):
            writes.append(account_obj)
            loop.call_soon_threadsafe(started.set)
            if not release.wait(timeout=5):
                raise TimeoutError('The event loop could not release the disk worker')
            persist(account_obj)

        monkeypatch.setattr(account_storage, '_persist_new_account', delayed_write)
        first = asyncio.create_task(server.storage.get_or_create_account('cancelled'))
        try:
            await asyncio.wait_for(started.wait(), timeout=1)
            for _ in range(cancel_count):
                first.cancel()
                turn = loop.create_future()
                loop.call_soon(turn.set_result, None)
                await turn
                assert not first.done()
                assert server.storage._creation_lock.locked()
                assert writes[0].lock.locked()
            second = asyncio.create_task(server.storage.get_or_create_account('cancelled'))
        finally:
            release.set()
        results = await asyncio.wait_for(
            asyncio.gather(first, second, return_exceptions=True), timeout=2,
        )
        assert isinstance(results[0], asyncio.CancelledError)
        assert results[1] is server.storage.require_account('cancelled')
        assert writes == [results[1]]
        assert AccountStorage().get_account('cancelled') is not None

    @pytest.mark.asyncio
    async def test_register_reuses_legacy_account_name(
        self, temp_accounts_storage, async_client, server,
    ):
        path = temp_accounts_storage / 'legacy.office.json'
        document = {'payload': [], 'updated_at': 0.0, 'revision': 0}
        path.write_text(json.dumps(document))
        server.storage = AccountStorage()
        with patch.object(Account, 'write_file', side_effect=AssertionError('must reuse existing file')):
            response = await async_client.send_request(register_payload('legacy.office'))
        assert response[Fields.result] is True
        assert response[Fields.payload] == []
        assert json.loads(path.read_text()) == document

    @pytest.mark.asyncio
    async def test_register_waits_for_account_lock(self, server, account, async_client):
        """Второй клиент должен ждать, пока аккаунт залочен."""
        account_obj = await server.storage.get_or_create_account(account)
        waiter_arrived = asyncio.Event()

        class ObservedLock(asyncio.Lock):
            async def acquire(self):
                if self.locked():
                    waiter_arrived.set()
                return await super().acquire()

        account_obj.lock = ObservedLock()
        await account_obj.lock.acquire()
        try:
            register_task = asyncio.create_task(
                async_client.send_request(register_payload(account))
            )
            await asyncio.wait_for(waiter_arrived.wait(), timeout=1)
            assert not register_task.done()
            assert not server.storage.websockets_by_account.get(account)
        finally:
            account_obj.lock.release()

        response = await asyncio.wait_for(register_task, timeout=1)
        assert response[Fields.result] is True
        assert server.storage.websockets_by_account.get(account)

    @pytest.mark.asyncio
    async def test_unknown_command(self, server, account, async_client):
        command_name = 'no_such_command'
        response = await async_client.send_request({
            Fields.command: command_name,
            Fields.account: account,
        })
        assert response[Fields.result] is False
        assert command_name in response[Fields.message]
        assert response[Fields.uuid] == async_client.last_request_uuid

    @pytest.mark.asyncio
    async def test_set(self, server, cookies_not_sample, account, async_client, second_client):
        await async_client.send_request(register_payload(account))
        await second_client.send_request(register_payload(account))

        # регистрация прошла успешно у обоих клиентов
        assert len(server.storage.websockets_by_account.get(account)) == 2
        assert server.storage.get_account(account).payload != cookies_not_sample

        response = await async_client.send_request(set_payload(account, cookies_not_sample))
        assert response[Fields.result] is True
        assert response[Fields.accepted] is True
        assert response[Fields.revision] == 1

        # сервер сохранил куки
        assert server.storage.get_account(account).payload == cookies_not_sample
        assert account in [acc.split('.')[0] for acc in os.listdir(ACCOUNTS_PATH)]

        # сервер разослал куки второму клиенту того же аккаунта
        received_data = await second_client.recv_server_message()
        assert received_data[Fields.payload] == cookies_not_sample

    @pytest.mark.asyncio
    async def test_set_filters_unrelated_cookies(
        self, server, cookies_not_sample, account, async_client, second_client,
    ):
        await async_client.send_request(register_payload(account))
        await second_client.send_request(register_payload(account))
        mixed_cookies = cookies_not_sample + [{
            'name': 'UnrelatedCookie',
            'value': 'must-not-be-synchronized',
            'domain': '.reso.ru',
            'path': '/',
        }, {
            'name': 'resooffice60',
            'value': 'wrong-case-must-not-be-synchronized',
            'domain': '.reso.ru',
            'path': '/',
        }]

        response = await async_client.send_request(set_payload(account, mixed_cookies))

        assert response[Fields.result] is True
        assert server.storage.get_account(account).payload == cookies_not_sample
        received_data = await second_client.recv_server_message()
        assert received_data[Fields.payload] == cookies_not_sample

    @pytest.mark.asyncio
    async def test_set_rejects_incomplete_cookie_pair(
        self, server, cookies_not_sample, account, async_client,
    ):
        await async_client.send_request(register_payload(account))

        response = await async_client.send_request(
            set_payload(account, cookies_not_sample[:1])
        )

        assert response[Fields.result] is False
        assert 'exactly one of each' in response[Fields.message]
        assert server.storage.require_account(account).payload == []

    @pytest.mark.asyncio
    async def test_set_rejects_cookie_without_required_fields(
        self, server, cookies_not_sample, account, async_client,
    ):
        await async_client.send_request(register_payload(account))
        malformed = [dict(cookie) for cookie in cookies_not_sample]
        malformed[0].pop('value')

        response = await async_client.send_request(set_payload(account, malformed))

        assert response[Fields.result] is False
        assert 'string value' in response[Fields.message]
        assert server.storage.require_account(account).payload == []

    @pytest.mark.asyncio
    async def test_set_rejects_empty_cookie_value(
        self, server, cookies_not_sample, account, async_client,
    ):
        await async_client.send_request(register_payload(account))
        malformed = [dict(cookie) for cookie in cookies_not_sample]
        malformed[0]['value'] = ''

        response = await async_client.send_request(set_payload(account, malformed))

        assert response[Fields.result] is False
        assert 'non-empty string value' in response[Fields.message]
        assert server.storage.require_account(account).payload == []

    @pytest.mark.asyncio
    async def test_set_does_not_broadcast_to_sender(
        self, server, cookies_not_sample, account, async_client, second_client,
    ):
        await async_client.send_request(register_payload(account))
        await second_client.send_request(register_payload(account))

        response = await async_client.send_request(set_payload(account, cookies_not_sample))
        assert response[Fields.result] is True

        # отправитель не должен получить копию своего же set
        with pytest.raises(TimeoutError):
            await async_client.recv_server_message(timeout=0.2)

    @pytest.mark.asyncio
    async def test_set_succeeds_when_peer_disconnects(
        self, server, cookies_not_sample, account, async_client, second_client,
    ):
        """Падение второго клиента не должно ломать set у первого."""
        await async_client.send_request(register_payload(account))
        await second_client.send_request(register_payload(account))
        await second_client.close()

        response = await async_client.send_request(set_payload(account, cookies_not_sample))
        assert response[Fields.result] is True
        assert server.storage.get_account(account).payload == cookies_not_sample

    @pytest.mark.asyncio
    async def test_set_duplicate_payload_is_idempotent(
        self, server, cookies_not_sample, account, async_client, second_client,
    ):
        """Повторная отправка идентичных куки — успех без записи и broadcast."""
        await async_client.send_request(register_payload(account))
        await second_client.send_request(register_payload(account))
        assert server.storage.get_account(account).payload != cookies_not_sample

        response = await async_client.send_request(set_payload(account, cookies_not_sample))
        assert response[Fields.result] is True

        received = await second_client.recv_server_message()
        assert received[Fields.payload] == cookies_not_sample

        duplicate = await async_client.send_request(set_payload(account, cookies_not_sample))
        assert duplicate[Fields.result] is True
        assert duplicate[Fields.accepted] is True
        assert duplicate[Fields.uuid] == async_client.last_request_uuid
        assert server.storage.get_account(account).payload == cookies_not_sample

        # повторный идентичный set не должен рассылаться другим клиентам
        with pytest.raises(TimeoutError):
            await second_client.recv_server_message(timeout=0.2)

    @pytest.mark.asyncio
    async def test_second_client_is_restored_during_update_interval(
        self, server, cookies_not_sample, cookies_other, account, async_client, second_client,
    ):
        """Вторая пара блокируется, а отправителю возвращается серверная."""
        await async_client.send_request(register_payload(account))
        await second_client.send_request(register_payload(account))

        first = await async_client.send_request(set_payload(account, cookies_not_sample))
        assert first[Fields.accepted] is True
        received_by_second = await second_client.recv_server_message()
        assert received_by_second[Fields.payload] == cookies_not_sample

        second = await second_client.send_request(set_payload(account, cookies_other))
        assert second[Fields.result] is True
        assert second[Fields.accepted] is False
        assert second[Fields.payload] == cookies_not_sample
        assert second[Fields.revision] == first[Fields.revision]
        assert second[Fields.retry_after] > 0
        assert server.storage.require_account(account).payload == cookies_not_sample

        with pytest.raises(TimeoutError):
            await async_client.recv_server_message(timeout=0.2)

    @pytest.mark.asyncio
    async def test_set_broadcasts_to_all_other_clients(
        self, server, cookies_not_sample, account, async_client, second_client, third_client,
    ):
        """Расс苍穹 на всех клиентов аккаунта кроме отправителя."""
        for client in (async_client, second_client, third_client):
            await client.send_request(register_payload(account))
        assert len(server.storage.websockets_by_account.get(account)) == 3

        response = await async_client.send_request(set_payload(account, cookies_not_sample))
        assert response[Fields.result] is True

        for client in (second_client, third_client):
            received = await client.recv_server_message()
            assert received[Fields.payload] == cookies_not_sample
        with pytest.raises(TimeoutError):
            await async_client.recv_server_message(timeout=0.2)

    @pytest.mark.asyncio
    async def test_set_persists_and_is_idempotent(
        self, server, cookies_not_sample, account, async_client, second_client,
    ):
        """Реальная запись в файл и идемпотентность без мока."""
        await async_client.send_request(register_payload(account))
        await second_client.send_request(register_payload(account))
        account_obj = server.storage.get_account(account)
        assert account_obj.payload != cookies_not_sample
        account_obj.updated_at = 0.0
        account_obj._locked_until = 0.0

        response = await async_client.send_request(set_payload(account, cookies_not_sample))
        assert response[Fields.result] is True
        assert account_obj.payload == cookies_not_sample
        updated_at_after_change = account_obj.updated_at

        # куки записаны на диск
        path = os.path.join(ACCOUNTS_PATH, f'{account}.json')
        with open(path) as f:
            document = json.loads(f.read())
        assert document[Fields.payload] == cookies_not_sample
        assert document['updated_at'] == updated_at_after_change
        assert document[Fields.revision] == 1

        reloaded_account = AccountStorage().require_account(account)
        assert reloaded_account.payload == cookies_not_sample
        assert reloaded_account.updated_at == updated_at_after_change
        assert reloaded_account.revision == 1
        with patch(
            'cookieserver.src.storage.time.monotonic',
            return_value=reloaded_account._locked_until - 1,
        ):
            blocked_after_restart = reloaded_account.set_payload(cookies_other)
        assert blocked_after_restart.accepted is False
        assert blocked_after_restart.retry_after == 1
        assert reloaded_account.payload == cookies_not_sample

        # второму клиенту пришла рассылка
        received = await second_client.recv_server_message()
        assert received[Fields.payload] == cookies_not_sample

        # повторный идентичный set: успех, без изменения updated_at и без рассылки
        duplicate = await async_client.send_request(set_payload(account, cookies_not_sample))
        assert duplicate[Fields.result] is True
        assert account_obj.updated_at == updated_at_after_change
        with pytest.raises(TimeoutError):
            await second_client.recv_server_message(timeout=0.2)

    @pytest.mark.asyncio
    async def test_failed_file_write_rolls_back_account_state(
        self, server, cookies_not_sample, account, async_client,
    ):
        await async_client.send_request(register_payload(account))
        account_obj: Account = server.storage.require_account(account)
        previous_payload = account_obj.payload
        previous_updated_at = account_obj.updated_at
        previous_revision = account_obj.revision

        with patch.object(account_obj, 'write_file', side_effect=OSError('disk full')):
            response = await async_client.send_request(
                set_payload(account, cookies_not_sample)
            )

        assert response[Fields.result] is False
        assert account_obj.payload == previous_payload
        assert account_obj.updated_at == previous_updated_at
        assert account_obj.revision == previous_revision

    @pytest.mark.asyncio
    async def test_new_pair_is_accepted_only_after_configured_interval(
        self, server, cookies_not_sample, cookies_other, account,
        async_client, second_client,
    ):
        """Окно фиксировано от записи и не сдвигается заблокированным set."""
        await async_client.send_request(register_payload(account))
        await second_client.send_request(register_payload(account))
        account_obj = server.storage.get_account(account)
        account_obj.updated_at = 0.0
        account_obj._locked_until = 0.0

        with patch('cookieserver.src.storage.time.time', return_value=1000.0), patch(
            'cookieserver.src.storage.time.monotonic', return_value=2000.0,
        ):
            first = await async_client.send_request(set_payload(account, cookies_not_sample))
        assert first[Fields.result] is True
        assert first[Fields.accepted] is True
        assert first[Fields.retry_after] == COOKIE_UPDATE_INTERVAL
        await second_client.recv_server_message()

        with patch(
            'cookieserver.src.storage.time.monotonic',
            return_value=2000.0 + COOKIE_UPDATE_INTERVAL - 1,
        ):
            second = await second_client.send_request(set_payload(account, cookies_other))
        assert second[Fields.result] is True
        assert second[Fields.accepted] is False
        assert second[Fields.retry_after] == 1
        assert second[Fields.payload] == cookies_not_sample
        assert account_obj.payload == cookies_not_sample
        assert account_obj.updated_at == 1000.0

        with patch(
            'cookieserver.src.storage.time.time',
            return_value=1000.0 + COOKIE_UPDATE_INTERVAL,
        ), patch(
            'cookieserver.src.storage.time.monotonic',
            return_value=2000.0 + COOKIE_UPDATE_INTERVAL,
        ):
            third = await second_client.send_request(set_payload(account, cookies_other))
        assert third[Fields.accepted] is True
        assert third[Fields.revision] == 2
        assert account_obj.payload == cookies_other
        received = await async_client.recv_server_message()
        assert received[Fields.payload] == cookies_other

    @pytest.mark.asyncio
    @pytest.mark.parametrize('omitted', [Fields.command, Fields.account, Fields.uuid])
    async def test_request_missing_required_field(self, server, account, async_client, omitted):
        """Запрос без обязательного поля отклоняется с указанием поля."""
        message = {
            Fields.command: Commands.register,
            Fields.account: account,
            Fields.uuid: 'req-uuid',
        }
        message.pop(omitted)
        await async_client.ws.send(json.dumps(message))
        response = await async_client.recv_server_message()
        assert response[Fields.result] is False
        assert omitted in response[Fields.message]

    @pytest.mark.asyncio
    async def test_double_register_same_connection_single_entry(
        self, server, account, async_client,
    ):
        """Повторный register на тот же аккаунт не должен дублировать клиента в сете."""
        await async_client.send_request(register_payload(account))
        await async_client.send_request(register_payload(account))
        assert len(server.storage.websockets_by_account.get(account)) == 1

    @pytest.mark.asyncio
    async def test_re_register_moves_client_between_accounts(
        self, server, account, other_account, async_client,
    ):
        """Повторный register на другой аккаунт убирает клиента из старого аккаунта."""
        first = await async_client.send_request(register_payload(account))
        assert first[Fields.result] is True
        assert len(server.storage.websockets_by_account.get(account)) == 1

        second = await async_client.send_request(register_payload(other_account))
        assert second[Fields.result] is True
        assert not server.storage.websockets_by_account.get(account)
        assert len(server.storage.websockets_by_account.get(other_account)) == 1

        await async_client.close()
        await self.wait_until(lambda: not server.storage.websockets_by_account.get(other_account))
        assert not server.storage._ws_accounts

    @pytest.mark.asyncio
    async def test_set_isolated_between_accounts(
        self, server, cookies_not_sample, account, other_account, async_client, second_client,
    ):
        """set в одном аккаунте не рассылается и не пишется в другой аккаунт."""
        await async_client.send_request(register_payload(account))
        await second_client.send_request(register_payload(other_account))

        response = await async_client.send_request(set_payload(account, cookies_not_sample))
        assert response[Fields.result] is True

        # клиент другого аккаунта не получает рассылку
        with pytest.raises(TimeoutError):
            await second_client.recv_server_message(timeout=0.2)
        # и куки не записались в другой аккаунт
        assert server.storage.get_account(other_account).payload != cookies_not_sample

    @pytest.mark.asyncio
    async def test_late_join_register_returns_current_cookies(
        self, server, cookies_not_sample, account, async_client, second_client, third_client,
    ):
        """Новый клиент при регистрации получает уже сохранённые куки аккаунта."""
        await async_client.send_request(register_payload(account))
        await second_client.send_request(register_payload(account))

        response = await async_client.send_request(set_payload(account, cookies_not_sample))
        assert response[Fields.result] is True

        # третий клиент подключается ПОСЛЕ set, но в ответе register получает текущие куки
        late = await third_client.send_request(register_payload(account))
        assert late[Fields.result] is True
        assert late[Fields.uuid] == third_client.last_request_uuid
        assert late[Fields.payload] == cookies_not_sample
        assert late[Fields.revision] == 1
        assert late[Fields.retry_after] > 0

    @pytest.mark.asyncio
    async def test_malformed_messages_do_not_kill_connection(
        self, server, account, async_client,
    ):
        """Битый JSON и JSON-не-объект дают result:false с uuid='' и не рвут соединение."""
        await async_client.send_raw('this is not json')
        response = await async_client.recv_server_message()
        assert response[Fields.result] is False
        assert response[Fields.uuid] == ''
        assert response[Fields.message] == 'Invalid message format'

        await async_client.send_raw('[1, 2, 3]')
        response = await async_client.recv_server_message()
        assert response[Fields.result] is False
        assert response[Fields.uuid] == ''

        # соединение живо и отвечает на нормальные запросы
        ok = await async_client.send_request(register_payload(account))
        assert ok[Fields.result] is True

    @pytest.mark.asyncio
    async def test_set_unknown_account_returns_false(
        self, server, cookies_not_sample, async_client,
    ):
        """set в несуществующий аккаунт → result:false, соединение не падает."""
        missing = 'definitely_not_there_account'
        assert server.storage.get_account(missing) is None

        response = await async_client.send_request(set_payload(missing, cookies_not_sample))
        assert response[Fields.result] is False
        assert response[Fields.uuid] == async_client.last_request_uuid
        assert 'does not exist' in response[Fields.message]
        assert server.storage.get_account(missing) is None

    @pytest.mark.asyncio
    async def test_server_push_has_command_set_and_no_uuid(
        self, server, cookies_not_sample, account, async_client, second_client,
    ):
        """Server push: command='set', payload=cookies и НИКАКОГО uuid (протокол)."""
        await async_client.send_request(register_payload(account))
        await second_client.send_request(register_payload(account))

        response = await async_client.send_request(set_payload(account, cookies_not_sample))
        assert response[Fields.result] is True

        push = await second_client.recv_server_message()
        assert push[Fields.command] == Commands.set
        assert push[Fields.payload] == cookies_not_sample
        assert push[Fields.revision] == 1
        assert Fields.uuid not in push

    def test_storage_skips_corrupt_account_file(self, tmp_path, monkeypatch):
        """Unreadable/битый JSON в accounts/ пропускается, остальные аккаунты грузятся."""
        accounts_dir = tmp_path / 'accounts'
        accounts_dir.mkdir()
        monkeypatch.setattr('cookieserver.src.storage.ACCOUNTS_PATH', str(accounts_dir))

        (accounts_dir / 'corrupt.json').write_text('{not valid json')
        (accounts_dir / 'ok_account.json').write_text('[]')

        storage = AccountStorage()
        assert storage.get_account('corrupt') is None
        assert storage.get_account('ok_account') is not None
        assert storage.get_all_accounts() == ['ok_account']

    def test_storage_missing_accounts_dir_does_not_crash(self, tmp_path, monkeypatch):
        """Сервер стартует даже если каталог accounts/ не существует."""
        missing = tmp_path / 'no_such_accounts_dir'
        monkeypatch.setattr('cookieserver.src.storage.ACCOUNTS_PATH', str(missing))

        storage = AccountStorage()
        assert storage.get_all_accounts() == []

    def test_storage_removes_unrelated_cookies_from_existing_file(
        self, tmp_path, monkeypatch, cookies_not_sample,
    ):
        accounts_dir = tmp_path / 'accounts'
        accounts_dir.mkdir()
        monkeypatch.setattr('cookieserver.src.storage.ACCOUNTS_PATH', str(accounts_dir))
        mixed_cookies = cookies_not_sample + [{
            'name': 'LegacyCookie',
            'value': 'must-be-removed',
            'domain': '.reso.ru',
            'path': '/',
        }]
        account_path = accounts_dir / 'legacy.json'
        account_path.write_text(json.dumps(mixed_cookies))

        storage = AccountStorage()

        assert storage.require_account('legacy').payload == cookies_not_sample
        document = json.loads(account_path.read_text())
        assert document[Fields.payload] == cookies_not_sample
        assert document['updated_at'] == 0.0
        assert document[Fields.revision] == 0

    def test_storage_incomplete_pair_does_not_keep_update_lock(
        self, tmp_path, monkeypatch, cookies_not_sample,
    ):
        accounts_dir = tmp_path / 'accounts'
        accounts_dir.mkdir()
        monkeypatch.setattr('cookieserver.src.storage.ACCOUNTS_PATH', str(accounts_dir))
        account_path = accounts_dir / 'incomplete.json'
        account_path.write_text(json.dumps({
            Fields.payload: cookies_not_sample[:1],
            'updated_at': 9999999999.0,
            Fields.revision: 12,
        }))

        account = AccountStorage().require_account('incomplete')

        assert account.payload == []
        assert account.updated_at == 0.0
        assert account.revision == 12
        assert account.retry_after() == 0

    @pytest.mark.asyncio
    async def test_tls_client_on_plain_server_logs_concisely(
        self, plain_server, caplog,
    ):
        """TLS-байты на ws://-сервере: краткая запись WARNING без traceback, сервер жив."""
        port = plain_server.server.sockets[0].getsockname()[1]

        account_name = 'post_tls_account'

        # Отправляем TLS ClientHello в незашифрованный сервер
        reader, writer = await asyncio.open_connection(HOST, port)
        writer.write(b'\x16\x03\x01\x00\x02' + b'\x01\x00')
        await writer.drain()
        writer.close()
        await writer.wait_closed()

        await self.wait_until(
            lambda: any(
                r.name == 'cookieserver.src.server'
                and 'opening handshake failed' in r.getMessage()
                for r in caplog.records
            )
        )

        handshake_records = [
            r for r in caplog.records
            if 'opening handshake failed' in r.getMessage()
        ]
        assert handshake_records
        assert all(r.levelname == 'WARNING' for r in handshake_records)
        assert all(r.exc_info is None for r in handshake_records)
        # сообщение должно явно подсказывать причину (wss:// клиент на ws:// сервере)
        assert all('wss://' in r.getMessage() for r in handshake_records)

        # сервер продолжает обслуживать обычных клиентов
        client = AsyncWSClient('after_tls')
        await client.connect(f'ws://{HOST}:{port}')
        try:
            response = await client.send_request(register_payload(account_name))
            assert response[Fields.result] is True
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_server_with_custom_cert_paths(self, tmp_path):
        """Сервер стартует с сертификатом из произвольных путей (--cert/--key)."""
        cert_path = os.path.join(tmp_path, 'custom_cert.pem')
        key_path = os.path.join(tmp_path, 'custom_key.pem')
        subprocess.run(
            [
                'openssl', 'req', '-newkey', 'rsa:2048', '-nodes',
                '-keyout', key_path, '-x509', '-days', '1',
                '-out', cert_path, '-subj', '/CN=custom-local',
            ],
            check=True,
            capture_output=True,
        )

        srv = Server(host=HOST, port=0, use_tls=True,
                     certfile=str(cert_path), keyfile=str(key_path))
        await srv.start()
        try:
            port = srv.server.sockets[0].getsockname()[1]
            client = AsyncWSClient('custom_cert_client')
            await client.connect(f'wss://{HOST}:{port}')
            try:
                account_name = 'custom_cert_account'
                response = await client.send_request(register_payload(account_name))
                assert response[Fields.result] is True
            finally:
                await client.close()
        finally:
            await srv.stop()


class TestManagementCommands:
    """Тесты management-команд manage.py (list_accounts, runserver)."""

    @pytest.fixture
    def manage_assets(self, tmp_path, monkeypatch):
        """Выделяет отдельный каталог аккаунтов для вызовов management-команд."""
        accounts_dir = tmp_path / 'accounts'
        accounts_dir.mkdir()
        monkeypatch.setattr('cookieserver.src.storage.ACCOUNTS_PATH', str(accounts_dir))
        return accounts_dir

    @pytest.mark.parametrize('command', ['create_account', 'remove_account'])
    def test_manual_account_commands_are_removed(self, command):
        with pytest.raises(SystemExit) as error:
            build_parser().parse_args([command, 'alice'])
        assert error.value.code == 2

    @pytest.mark.asyncio
    async def test_list_accounts(self, manage_assets, capsys):
        storage = AccountStorage()
        await storage.get_or_create_account('alice')
        await storage.get_or_create_account('bob')
        args = build_parser().parse_args(['list_accounts'])
        args.handler(args)
        out = capsys.readouterr().out
        assert 'alice' in out
        assert 'bob' in out

    def test_list_accounts_empty(self, manage_assets, capsys):
        args = build_parser().parse_args(['list_accounts'])
        args.handler(args)
        assert 'No accounts' in capsys.readouterr().out

    def test_help_command_lists_commands(self, manage_assets, capsys):
        args = build_parser().parse_args(['help'])
        args.handler(args)
        out = capsys.readouterr().out
        assert 'runserver' in out
        assert 'create_account' not in out
        assert 'list_accounts' in out
        assert 'remove_account' not in out

    def test_runserver_defaults_to_tls(self, manage_assets):
        args = build_parser().parse_args(['runserver', '--port', '0'])
        server = RunServerCommand().build_server(args)
        assert server.host == '0.0.0.0'
        assert server.use_tls is True
        assert server.certfile == KEYS_PATH + '/cert.pem'
        assert server.keyfile == KEYS_PATH + '/key.pem'

    def test_runserver_without_tls(self, manage_assets):
        args = build_parser().parse_args(['runserver', '--no-tls', '--port', '0'])
        server = RunServerCommand().build_server(args)
        assert server.use_tls is False
        assert server.certfile is None
        assert server.keyfile is None

    def test_runserver_custom_cert(self, manage_assets):
        args = build_parser().parse_args(
            ['runserver', '--port', '0', '--cert', '/tmp/c.pem', '--key', '/tmp/k.pem']
        )
        server = RunServerCommand().build_server(args)
        assert server.certfile == '/tmp/c.pem'
        assert server.keyfile == '/tmp/k.pem'


class TestRefreshCookies:
    """Compare-and-swap после входа: ревизии, cooldown, конкуренция и откат записи."""

    @staticmethod
    def request(account, cookies, revision):
        """Создаёт refresh с ожидаемой ревизией; корреляционный UUID добавит клиент."""
        return {
            Fields.command: Commands.refresh, Fields.account: account,
            Fields.payload: cookies, Fields.expected_revision: revision,
        }

    @pytest.mark.asyncio
    async def test_refresh_replaces_pair_during_cooldown_and_persists(
        self, server, account, async_client, second_client, cookies_not_sample, cookies_other,
    ):
        await async_client.send_request(register_payload(account))
        first = await async_client.send_request(set_payload(account, cookies_not_sample))
        await second_client.send_request(register_payload(account))
        assert server.storage.require_account(account).retry_after() > 0
        response = await async_client.send_request(self.request(account, cookies_other, first[Fields.revision]))
        assert response[Fields.result] is True
        assert response[Fields.accepted] is True
        assert response[Fields.uuid] == async_client.last_request_uuid
        assert response[Fields.revision] == 2
        assert response[Fields.payload] == cookies_other
        assert response[Fields.retry_after] == COOKIE_UPDATE_INTERVAL
        persisted = AccountStorage().require_account(account)
        assert persisted.payload == cookies_other
        assert persisted.revision == 2
        assert persisted.retry_after() > 0
        push = await second_client.recv_server_message()
        assert push[Fields.payload] == cookies_other
        assert push[Fields.command] == Commands.set
        assert Fields.uuid not in push
        assert async_client.server_messages.empty()

        before = server.storage.require_account(account).updated_at
        duplicate = await async_client.send_request(self.request(account, cookies_other, 1))
        assert duplicate[Fields.accepted] is False
        assert duplicate[Fields.revision] == 2
        assert server.storage.require_account(account).updated_at == before
        assert second_client.server_messages.empty()

    @pytest.mark.asyncio
    async def test_refresh_conflict_is_rejected_even_after_cooldown(
        self, server, account, async_client, cookies_not_sample, cookies_other,
    ):
        await async_client.send_request(register_payload(account))
        await async_client.send_request(set_payload(account, cookies_not_sample))
        await async_client.send_request(self.request(account, cookies_other, 1))
        account_obj = server.storage.require_account(account)
        account_obj._locked_until = 0
        response = await async_client.send_request(self.request(account, cookies_not_sample, 1))
        assert response[Fields.result] is True
        assert response[Fields.accepted] is False
        assert response[Fields.uuid] == async_client.last_request_uuid
        assert response[Fields.payload] == cookies_other
        assert response[Fields.revision] == 2
        assert response[Fields.retry_after] == 0
        assert 'revision changed' in response[Fields.message]

    @pytest.mark.asyncio
    async def test_concurrent_refreshes_have_exactly_one_winner(
        self, server, account, async_client, second_client, cookies_not_sample, cookies_other,
    ):
        await async_client.send_request(register_payload(account))
        await async_client.send_request(set_payload(account, cookies_not_sample))
        await second_client.send_request(register_payload(account))
        alternate = [dict(cookie, value=cookie['value'] + '-another') for cookie in cookies_other]
        first, second = await asyncio.gather(
            async_client.send_request(self.request(account, cookies_other, 1)),
            second_client.send_request(self.request(account, alternate, 1)),
        )
        assert sorted([first[Fields.accepted], second[Fields.accepted]]) == [False, True]
        assert first[Fields.uuid] == async_client.last_request_uuid
        assert second[Fields.uuid] == second_client.last_request_uuid
        winner = cookies_other if first[Fields.accepted] else alternate
        assert first[Fields.payload] == second[Fields.payload] == winner
        assert first[Fields.revision] == second[Fields.revision] == 2
        assert AccountStorage().require_account(account).payload == winner
        loser = second_client if first[Fields.accepted] else async_client
        push = await loser.recv_server_message()
        assert push[Fields.payload] == winner
        assert Fields.uuid not in push

    @pytest.mark.asyncio
    @pytest.mark.parametrize('revision', [None, True, False, -1, 1.5, '1', [], {}])
    async def test_invalid_expected_revision_is_rejected(
        self, server, account, async_client, cookies_not_sample, revision,
    ):
        await async_client.send_request(register_payload(account))
        request = self.request(account, cookies_not_sample, revision)
        if revision is None:
            request.pop(Fields.expected_revision)
        response = await async_client.send_request(request)
        assert response[Fields.result] is False
        assert response[Fields.uuid] == async_client.last_request_uuid
        assert 'expected_revision' in response[Fields.message]
        assert server.storage.require_account(account).revision == 0

    @pytest.mark.asyncio
    async def test_refresh_requires_registration_in_target_account(
        self, server, account, other_account, async_client, second_client, cookies_not_sample,
    ):
        await async_client.send_request(register_payload(account))
        response = await second_client.send_request(self.request(account, cookies_not_sample, 0))
        assert response[Fields.result] is False
        await second_client.send_request(register_payload(other_account))
        response = await second_client.send_request(self.request(account, cookies_not_sample, 0))
        assert response[Fields.result] is False
        assert response[Fields.uuid] == second_client.last_request_uuid
        assert 'Register' in response[Fields.message]
        assert server.storage.require_account(account).payload == []

    @pytest.mark.asyncio
    async def test_regular_set_cannot_bypass_cooldown_by_adding_revision(
        self, server, account, async_client, cookies_not_sample, cookies_other,
    ):
        await async_client.send_request(register_payload(account))
        await async_client.send_request(set_payload(account, cookies_not_sample))
        request = set_payload(account, cookies_other)
        request[Fields.expected_revision] = 1
        response = await async_client.send_request(request)
        assert response[Fields.accepted] is False
        assert response[Fields.payload] == cookies_not_sample
        assert response[Fields.revision] == 1

    @pytest.mark.asyncio
    async def test_failed_refresh_write_rolls_back_and_can_be_retried(
        self, server, account, async_client, second_client, cookies_not_sample, cookies_other,
    ):
        await async_client.send_request(register_payload(account))
        await async_client.send_request(set_payload(account, cookies_not_sample))
        await second_client.send_request(register_payload(account))
        account_obj: Account = server.storage.require_account(account)
        before = (account_obj.updated_at, account_obj.revision, account_obj._locked_until)
        with patch.object(account_obj, 'write_file', side_effect=OSError('disk full')):
            response = await async_client.send_request(self.request(account, cookies_other, 1))
        assert response[Fields.result] is False
        assert response[Fields.message] == 'Internal server error'
        assert response[Fields.uuid] == async_client.last_request_uuid
        assert (account_obj.updated_at, account_obj.revision, account_obj._locked_until) == before
        assert account_obj.payload == cookies_not_sample
        assert second_client.server_messages.empty()
        response = await async_client.send_request(self.request(account, cookies_other, 1))
        assert response[Fields.accepted] is True
        assert response[Fields.revision] == 2

    @pytest.mark.asyncio
    async def test_refresh_waits_for_account_lock(
        self, server, account, async_client, cookies_not_sample, cookies_other,
    ):
        await async_client.send_request(register_payload(account))
        await async_client.send_request(set_payload(account, cookies_not_sample))
        waiting = asyncio.Event()

        class ObservedLock(asyncio.Lock):
            async def acquire(self):
                if self.locked():
                    waiting.set()
                return await super().acquire()

        account_obj = server.storage.require_account(account)
        account_obj.lock = ObservedLock()
        await account_obj.lock.acquire()
        try:
            request = asyncio.create_task(async_client.send_request(self.request(account, cookies_other, 1)))
            await asyncio.wait_for(waiting.wait(), timeout=1)
            assert not request.done()
            assert account_obj.payload == cookies_not_sample
        finally:
            account_obj.lock.release()
        response = await asyncio.wait_for(request, timeout=1)
        assert response[Fields.accepted] is True


class TestAuditRegressions:
    """Регрессии загрузки данных, регистрации и отмены фоновых файловых записей."""

    def test_list_accounts_never_rewrites_live_storage(self, temp_accounts_storage, cookies_not_sample, capsys):
        path = temp_accounts_storage / 'expired.json'
        document = json.dumps({
            'payload': [dict(cookie, expirationDate=1) for cookie in cookies_not_sample],
            'updated_at': 1, 'revision': 17,
        })
        path.write_text(document)
        args = build_parser().parse_args(['list_accounts'])
        args.handler(args)
        assert 'expired' in capsys.readouterr().out
        assert path.read_text() == document

    @pytest.mark.asyncio
    async def test_expiry_cleanup_never_reuses_a_revision(
        self, server, async_client, second_client, temp_accounts_storage, cookies_not_sample, cookies_other,
    ):
        path = temp_accounts_storage / 'expired.json'
        path.write_text(json.dumps({
            'payload': [dict(cookie, expirationDate=1) for cookie in cookies_not_sample],
            'updated_at': 1, 'revision': 1,
        }))
        server.storage = AccountStorage()
        account = server.storage.require_account('expired')
        assert account.payload == []
        assert account.revision == 1
        assert account.retry_after() == 0
        assert json.loads(path.read_text())['revision'] == 1
        assert AccountStorage().require_account('expired').revision == 1

        await async_client.send_request(register_payload('expired'))
        winner = await async_client.send_request(set_payload('expired', cookies_other))
        assert winner[Fields.accepted] is True
        assert winner[Fields.revision] == 2
        await second_client.send_request(register_payload('expired'))
        stale = await second_client.send_request(TestRefreshCookies.request('expired', cookies_not_sample, 1))
        assert stale[Fields.result] is True
        assert stale[Fields.accepted] is False
        assert stale[Fields.uuid] == second_client.last_request_uuid
        assert stale[Fields.revision] == 2
        assert stale[Fields.payload] == cookies_other
        assert AccountStorage().require_account('expired').payload == cookies_other

    @pytest.mark.parametrize('field,value', [('sameSite', []), ('sameSite', {}), ('name', []), ('expirationDate', 10 ** 1000)])
    def test_malformed_cookie_types_do_not_prevent_loading_other_accounts(
        self, temp_accounts_storage, cookies_not_sample, field, value,
    ):
        malformed = [dict(cookie) for cookie in cookies_not_sample]
        malformed[0][field] = value
        (temp_accounts_storage / 'bad.json').write_text(json.dumps({
            'payload': malformed, 'updated_at': 0, 'revision': 7,
        }))
        (temp_accounts_storage / 'healthy.json').write_text(json.dumps({
            'payload': cookies_not_sample, 'updated_at': 0, 'revision': 4,
        }))
        loaded = AccountStorage()
        assert loaded.require_account('bad').payload == []
        assert loaded.require_account('bad').revision == 7
        assert loaded.require_account('healthy').payload == cookies_not_sample
        assert loaded.require_account('healthy').revision == 4

    @pytest.mark.asyncio
    @pytest.mark.parametrize('field,value', [('sameSite', []), ('name', {}), ('expirationDate', 10 ** 1000)])
    async def test_malformed_cookie_types_are_protocol_errors(
        self, server, account, async_client, cookies_not_sample, field, value,
    ):
        await async_client.send_request(register_payload(account))
        malformed = [dict(cookie) for cookie in cookies_not_sample]
        malformed[0][field] = value
        response = await async_client.send_request(set_payload(account, malformed))
        assert response[Fields.result] is False
        assert response[Fields.uuid] == async_client.last_request_uuid
        assert response[Fields.message] != 'Internal server error'
        assert server.storage.require_account(account).revision == 0

    def test_unreadable_encoding_does_not_prevent_startup(self, temp_accounts_storage):
        path = temp_accounts_storage / 'bad.json'
        path.write_bytes(b'\xff\xfeinvalid')
        (temp_accounts_storage / 'healthy.json').write_text('[]')
        loaded = AccountStorage()
        assert loaded.get_all_accounts() == ['healthy']
        assert path.read_bytes() == b'\xff\xfeinvalid'

    @pytest.mark.parametrize('revision', [-1, True, '7', None])
    def test_invalid_revision_is_not_silently_reset(
        self, temp_accounts_storage, cookies_not_sample, revision,
    ):
        path = temp_accounts_storage / 'bad.json'
        original = json.dumps({'payload': cookies_not_sample, 'updated_at': 0, 'revision': revision})
        path.write_text(original)
        (temp_accounts_storage / 'healthy.json').write_text('[]')
        loaded = AccountStorage()
        assert loaded.get_account('bad') is None
        assert loaded.get_account('healthy') is not None
        assert path.read_text() == original

    @pytest.mark.asyncio
    @pytest.mark.parametrize('registered_elsewhere', [False, True])
    async def test_set_requires_registration_in_its_target_account(
        self, server, account, async_client, second_client, cookies_not_sample, registered_elsewhere,
    ):
        await async_client.send_request(register_payload(account))
        if registered_elsewhere:
            await second_client.send_request(register_payload('other_account'))
        response = await second_client.send_request(set_payload(account, cookies_not_sample))
        assert response[Fields.result] is False
        assert response[Fields.uuid] == second_client.last_request_uuid
        assert 'Register' in response[Fields.message]
        assert Fields.payload not in response
        assert server.storage.require_account(account).payload == []
        legitimate = await async_client.send_request(set_payload(account, cookies_not_sample))
        assert legitimate[Fields.accepted] is True

    @pytest.mark.asyncio
    async def test_disk_write_does_not_block_other_accounts(
        self, server, account, async_client, second_client, cookies_not_sample,
    ):
        await async_client.send_request(register_payload(account))
        account_obj: Account = server.storage.require_account(account)
        started = asyncio.Event()
        release = threading.Event()
        loop = asyncio.get_running_loop()
        original_write = account_obj.write_file

        def delayed_write():
            loop.call_soon_threadsafe(started.set)
            if not release.wait(timeout=5):
                raise TimeoutError('The event loop could not release the disk worker')
            original_write()

        with patch.object(account_obj, 'write_file', side_effect=delayed_write):
            writing = asyncio.create_task(async_client.send_request(set_payload(account, cookies_not_sample)))
            try:
                await asyncio.wait_for(started.wait(), timeout=3)
                registered = await second_client.send_request(register_payload('independent_account'))
                assert registered[Fields.result] is True
                response = await second_client.send_request(set_payload('independent_account', cookies_not_sample))
                assert response[Fields.accepted] is True
                assert not writing.done()
            finally:
                release.set()
                result = await writing
        assert result[Fields.accepted] is True

    @pytest.mark.asyncio
    @pytest.mark.parametrize('cancel_count', [1, 3])
    async def test_cancellation_keeps_account_locked_until_disk_write_finishes(
        self, server, account, async_client, cookies_not_sample, cancel_count,
    ):
        await async_client.send_request(register_payload(account))
        account_obj: Account = server.storage.require_account(account)
        websocket = next(iter(server.storage.websockets_by_account[account]))
        started = asyncio.Event()
        attempted = asyncio.Event()
        acquired = asyncio.Event()
        release = threading.Event()
        loop = asyncio.get_running_loop()
        original_write = account_obj.write_file

        class ObservedLock(asyncio.Lock):
            async def acquire(self):
                if self.locked():
                    attempted.set()
                return await super().acquire()

        account_obj.lock = ObservedLock()

        def delayed_write():
            loop.call_soon_threadsafe(started.set)
            if not release.wait(timeout=5):
                raise TimeoutError('The event loop could not release the disk worker')
            original_write()

        async def follow():
            async with account_obj.lock:
                acquired.set()

        with patch.object(account_obj, 'write_file', side_effect=delayed_write):
            request = Request({**set_payload(account, cookies_not_sample), Fields.uuid: 'cancelled-write'})
            writing = asyncio.create_task(SetCookiesCommand().execute(server.storage, request, websocket))
            follower = None
            try:
                await asyncio.wait_for(started.wait(), timeout=3)
                for _ in range(cancel_count):
                    writing.cancel()
                    turn = loop.create_future()
                    loop.call_soon(turn.set_result, None)
                    await turn
                    assert not writing.done()
                    assert account_obj.lock.locked()
                follower = asyncio.create_task(follow())
                await asyncio.wait_for(attempted.wait(), timeout=3)
                assert not acquired.is_set()
            finally:
                release.set()
                with pytest.raises(asyncio.CancelledError):
                    await writing
                if follower:
                    await follower
        assert acquired.is_set()
        assert AccountStorage().require_account(account).payload == cookies_not_sample

    @pytest.mark.asyncio
    async def test_failed_write_after_repeated_cancel_rolls_back_and_preserves_cancellation(
        self, server, account, async_client, cookies_not_sample, caplog,
    ):
        await async_client.send_request(register_payload(account))
        account_obj: Account = server.storage.require_account(account)
        websocket = next(iter(server.storage.websockets_by_account[account]))
        started = asyncio.Event()
        finished = asyncio.Event()
        release = threading.Event()
        loop = asyncio.get_running_loop()

        def failed_write():
            loop.call_soon_threadsafe(started.set)
            try:
                if not release.wait(timeout=5):
                    raise TimeoutError('The event loop could not release the disk worker')
                raise OSError('disk full')
            finally:
                loop.call_soon_threadsafe(finished.set)

        with patch.object(account_obj, 'write_file', side_effect=failed_write):
            request = Request({**set_payload(account, cookies_not_sample), Fields.uuid: 'cancelled-failed-write'})
            writing = asyncio.create_task(SetCookiesCommand().execute(server.storage, request, websocket))
            try:
                await asyncio.wait_for(started.wait(), timeout=3)
                for _ in range(3):
                    writing.cancel()
                    turn = loop.create_future()
                    loop.call_soon(turn.set_result, None)
                    await turn
                    assert account_obj.lock.locked()
                    assert not writing.done()
            finally:
                release.set()
                with pytest.raises(asyncio.CancelledError):
                    await writing
                await asyncio.wait_for(finished.wait(), timeout=3)
        assert account_obj.payload == []
        assert account_obj.revision == 0
        assert not account_obj.lock.locked()
        assert AccountStorage().require_account(account).payload == []
        assert 'Storage operation failed while cancellation was pending' in caplog.text

    @pytest.mark.asyncio
    async def test_failed_creation_after_repeated_cancel_is_not_published(self, server, monkeypatch, caplog):
        account_storage: AccountStorage = server.storage
        started = asyncio.Event()
        finished = asyncio.Event()
        release = threading.Event()
        loop = asyncio.get_running_loop()
        original = account_storage._persist_new_account

        def failed_create(_account):
            loop.call_soon_threadsafe(started.set)
            try:
                if not release.wait(timeout=5):
                    raise TimeoutError('The event loop could not release the disk worker')
                raise OSError('disk full')
            finally:
                loop.call_soon_threadsafe(finished.set)

        monkeypatch.setattr(account_storage, '_persist_new_account', failed_create)
        creating = asyncio.create_task(server.storage.get_or_create_account('cancelled_failure'))
        try:
            await asyncio.wait_for(started.wait(), timeout=3)
            for _ in range(3):
                creating.cancel()
                turn = loop.create_future()
                loop.call_soon(turn.set_result, None)
                await turn
                assert server.storage._creation_lock.locked()
                assert not creating.done()
        finally:
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await creating
            await asyncio.wait_for(finished.wait(), timeout=3)
        assert server.storage.get_account('cancelled_failure') is None
        assert not server.storage._creation_lock.locked()
        assert 'Storage operation failed while cancellation was pending' in caplog.text
        monkeypatch.setattr(account_storage, '_persist_new_account', original)
        created = await server.storage.get_or_create_account('cancelled_failure')
        assert created is server.storage.require_account('cancelled_failure')

    @pytest.mark.asyncio
    async def test_storage_completion_is_not_cancelled_by_a_task_shutdown_sweep(self):
        loop = asyncio.get_running_loop()
        before = asyncio.all_tasks()
        started = asyncio.Event()
        release = threading.Event()
        lock = asyncio.Lock()
        published = []

        def work():
            loop.call_soon_threadsafe(started.set)
            if not release.wait(timeout=5):
                raise TimeoutError('The event loop could not release the disk worker')
            return 'committed'

        async def write():
            async with lock:
                await run_storage_write(work, on_success=published.append)

        writing = asyncio.create_task(write())
        try:
            await asyncio.wait_for(started.wait(), timeout=3)
            tasks = asyncio.all_tasks() - before
            # A separately cancellable to_thread Task would lose the completion
            # signal during asyncio.run() shutdown even if its parent shields it.
            assert tasks == {writing}
            for task in tasks:
                task.cancel()
            turn = loop.create_future()
            loop.call_soon(turn.set_result, None)
            await turn
            assert lock.locked()
            assert not writing.done()
        finally:
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await writing
        assert published == ['committed']
        assert not lock.locked()
