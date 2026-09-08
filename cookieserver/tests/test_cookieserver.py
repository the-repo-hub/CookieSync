"""Test module for CookieServer."""
import asyncio
import json
import os
import subprocess
from unittest.mock import patch

import pytest
import pytest_asyncio

from cookieserver.src.choices import Commands, Fields
from cookieserver.src.server import Server
from cookieserver.src.settings import ACCOUNTS_PATH, COOKIE_SERVER_PATH, KEYS_PATH
from cookieserver.tests.AsyncWSClient import AsyncWSClient

HOST = '127.0.0.1'


@pytest.fixture(scope='session', autouse=True)
def asset_dirs():
    """Предусловия для тестов: каталоги хранилища и TLS-сертификат."""
    os.makedirs(ACCOUNTS_PATH, exist_ok=True)
    os.makedirs(KEYS_PATH, exist_ok=True)

    cert_path = os.path.join(KEYS_PATH, 'cert.pem')
    key_path = os.path.join(KEYS_PATH, 'key.pem')
    if not (os.path.exists(cert_path) and os.path.exists(key_path)):
        subprocess.run(
            [
                'openssl', 'req', '-newkey', 'rsa:2048', '-nodes',
                '-keyout', key_path, '-x509', '-days', '365',
                '-out', cert_path, '-subj', '/CN=localhost',
            ],
            check=True,
            capture_output=True,
        )


@pytest.fixture
def cookies_not_sample():
    """Куки, которых точно нет на сервере"""
    with open(os.path.join(COOKIE_SERVER_PATH, "tests/test_cookie.json")) as f:
        cookies = json.loads(f.read())
    cookies[0]['value'] = "value_not_sample"
    yield cookies


@pytest_asyncio.fixture
async def server():
    server = Server(host=HOST, port=0)
    await server.start()
    try:
        yield server
    finally:
        await server.stop()


@pytest.fixture
def server_url(server):
    sock = server.server.sockets[0]
    port = sock.getsockname()[1]
    return f'wss://{HOST}:{port}'


@pytest_asyncio.fixture
async def async_client(server_url):
    client = AsyncWSClient('async_client')
    await client.connect(server_url)
    yield client
    await client.close()


@pytest_asyncio.fixture
async def second_client(server_url):
    client = AsyncWSClient('second_client')
    await client.connect(server_url)
    yield client
    await client.close()


@pytest.fixture
def not_storage_account(server):
    account = 'test_to_create'
    yield account
    if account in server.storage.get_all_accounts():
        server.storage.remove_account(account)


@pytest.fixture
def account(server):
    test_account_name = 'test_account'
    if test_account_name in server.storage.get_all_accounts():
        server.storage.remove_account(test_account_name)
    server.storage.add_account(test_account_name)
    yield test_account_name
    if test_account_name in server.storage.get_all_accounts():
        server.storage.remove_account(test_account_name)


def make_fake():
    def fake(self, payload):
        self.payload = payload
        self.updated_at = 0
        self.write_file()
    return fake


def register_payload(account):
    return {
        Fields.command: Commands.register,
        Fields.account: account,
    }


def set_payload(account, cookies):
    return {
        Fields.command: Commands.set,
        Fields.account: account,
        Fields.payload: cookies,
    }


class TestCookieServer:
    """Test class for CookieServer."""

    async def wait_until(self, predicate, timeout=1, interval=0.01):
        start = asyncio.get_running_loop().time()
        while True:
            if predicate():
                return
            if asyncio.get_running_loop().time() - start > timeout:
                raise TimeoutError("Condition not met")
            await asyncio.sleep(interval)

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
    async def test_register_failed(self, server, async_client, not_storage_account):
        # аккаунта нет на сервере, регистрация должна провалиться
        response = await async_client.send_request(register_payload(not_storage_account))
        assert response[Fields.result] is False
        assert response[Fields.uuid] == async_client.last_request_uuid
        assert not server.storage.websockets_by_account.get(not_storage_account)

    @pytest.mark.asyncio
    async def test_register_waits_for_account_lock(self, server, account, async_client):
        """Второй клиент должен ждать, пока аккаунт залочен."""
        account_obj = server.storage.require_account(account)
        await account_obj.lock.acquire()
        try:
            register_task = asyncio.create_task(
                async_client.send_request(register_payload(account))
            )
            # даём запросу дойти до блокировки на аккаунте
            await asyncio.sleep(0.1)
            assert not register_task.done()
            assert not server.storage.websockets_by_account.get(account)
        finally:
            account_obj.lock.release()

        response = await asyncio.wait_for(register_task, timeout=1)
        assert response[Fields.result] is True
        assert server.storage.websockets_by_account.get(account)

    @pytest.mark.asyncio
    async def test_ping(self, server, async_client):
        response = await async_client.send_request({Fields.command: 'ping'})
        assert response[Fields.command] == 'pong'
        assert response[Fields.uuid] == async_client.last_request_uuid

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

        fake_set_payload = make_fake()
        with patch("cookieserver.src.storage.Account.set_payload", new=fake_set_payload):
            response = await async_client.send_request(set_payload(account, cookies_not_sample))
        assert response[Fields.result] is True

        # сервер сохранил куки
        assert server.storage.get_account(account).payload == cookies_not_sample
        assert account in [acc.split('.')[0] for acc in os.listdir(ACCOUNTS_PATH)]

        # сервер разослал куки второму клиенту того же аккаунта
        received_data = await second_client.recv_server_message()
        assert received_data[Fields.payload] == cookies_not_sample

    @pytest.mark.asyncio
    async def test_set_does_not_broadcast_to_sender(
        self, server, cookies_not_sample, account, async_client, second_client,
    ):
        await async_client.send_request(register_payload(account))
        await second_client.send_request(register_payload(account))

        fake_set_payload = make_fake()
        with patch("cookieserver.src.storage.Account.set_payload", new=fake_set_payload):
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

        fake_set_payload = make_fake()
        with patch("cookieserver.src.storage.Account.set_payload", new=fake_set_payload):
            response = await async_client.send_request(set_payload(account, cookies_not_sample))
        assert response[Fields.result] is True
        assert server.storage.get_account(account).payload == cookies_not_sample

    @pytest.mark.asyncio
    async def test_set_rejects_duplicate_payload(
        self, server, cookies_not_sample, account, async_client,
    ):
        """Реальный set_payload: идентичные куки должны провалиться."""
        await async_client.send_request(register_payload(account))
        assert server.storage.get_account(account).payload != cookies_not_sample

        response = await async_client.send_request(set_payload(account, cookies_not_sample))
        assert response[Fields.result] is True

        duplicate = await async_client.send_request(set_payload(account, cookies_not_sample))
        assert duplicate[Fields.result] is False
        assert 'Payload is same' in duplicate[Fields.message]
        assert duplicate[Fields.uuid] == async_client.last_request_uuid