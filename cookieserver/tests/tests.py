"""Test module for CookieServer."""
import asyncio
import json
import os
from unittest.mock import patch

import pytest
import pytest_asyncio

from cookieserver.src.choices import Commands, Fields
from cookieserver.src.server import Server
from cookieserver.src.settings import ACCOUNTS_PATH, COOKIE_SERVER_PATH
from cookieserver.tests.AsyncWSClient import AsyncWSClient

SERVER_PORT = 52314
SERVER_ADDRESS = '127.0.0.1'
URL = f'wss://{SERVER_ADDRESS}:{SERVER_PORT}'

@pytest.fixture(scope='class')
def cookies_not_sample():
    """Куки, которых точно нет на сервере"""
    with open(os.path.join(COOKIE_SERVER_PATH, "tests/test_cookie.json")) as f:
        cookies = json.loads(f.read())
    cookies[0]['value'] = "value_not_sample"
    yield cookies

@pytest_asyncio.fixture
async def server():
    server = Server(host=SERVER_ADDRESS, port=SERVER_PORT)
    await server.start()
    try:
        yield server
    finally:
        await server.stop()

@pytest.fixture
def not_storage_account(server):
    account = 'test_to_create'
    yield account
    try:
        server.storage.remove_account(account)
    except Exception:
        pass

@pytest.fixture
def account(server, cookies_not_sample):
    test_account_name = 'test_account'
    if test_account_name in server.storage.get_all_accounts():
        server.storage.remove_account(test_account_name)
    server.storage.add_account(test_account_name)
    yield test_account_name
    try:
        server.storage.remove_account(test_account_name)
    except Exception:
        pass

@pytest_asyncio.fixture
async def async_client(server):
    """Async client fixture."""
    client = AsyncWSClient('test_client')
    await client.connect(URL)
    yield client
    await client.close()

def make_fake():
    def fake(self, payload):
        self.payload = payload
        self.updated_at = 0
        self.write_file()
    return fake

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
        payload = {
            Fields.command: Commands.register,
            Fields.account: account,
        }
        response = await async_client.send_request(payload)
        assert response[Fields.result]
        assert server.storage.websockets_by_account.get(account)
        assert response[Fields.payload] == server.storage.get_account(account).payload

        # закрываем соединение, в это время сервер должен выкинуть клиента из списка
        await async_client.close()
        await self.wait_until(lambda: not server.storage.websockets_by_account.get(account))

    @pytest.mark.asyncio
    async def test_register_failed(self, server, async_client, not_storage_account):
        #there is no that cookie on server, so server cant do it
        payload = {
            Fields.command: Commands.register,
            Fields.account: not_storage_account,
        }
        response = await async_client.send_request(payload)
        assert not response[Fields.result]
        assert not server.storage.websockets_by_account.get(not_storage_account)

    @pytest.mark.asyncio
    async def test_set(self, server, cookies_not_sample, account, async_client):
        """Simple set"""

        async_client_2 = AsyncWSClient('client_2')
        await async_client_2.connect(URL)
        await async_client.send_request(
            payload={
                Fields.command: Commands.register,
                Fields.account: account,
            }
        )
        await async_client_2.send_request(
            payload={
                Fields.command: Commands.register,
                Fields.account: account
            }
        )

        # регистрация прошла успешно
        assert len(server.storage.websockets_by_account.get(account)) == 2

        # куки не изменены
        assert server.storage.get_account(account).payload != cookies_not_sample

        fake_set_payload = make_fake()
        with patch("cookieserver.src.storage.Account.set_payload", new=fake_set_payload):
            response = await async_client.send_request(
                payload={
                    Fields.command: Commands.set,
                    Fields.account: account,
                    Fields.payload: cookies_not_sample,
                }
            )
        assert response[Fields.result] is True
        # проверки на то, что обычное изменение кук работает
        assert server.storage.get_account(account).payload == cookies_not_sample
        assert account in [acc.split('.')[0] for acc in os.listdir(ACCOUNTS_PATH)]

        # проверки на то, что сервер отправил куки второму клиенту и они были корректно приняты
        received_data = await async_client_2.recv_server_message(5)
        assert received_data[Fields.payload] == cookies_not_sample
        await async_client_2.close()

    @pytest.mark.asyncio
    async def test_set_failed(self, server, cookies_not_sample, async_client, account):
        """Тест на падение одного из клиентов"""
        client_failed = AsyncWSClient('client_failed')
        await client_failed.connect(URL)
        await async_client.send_request(
            payload={
                Fields.command: Commands.register,
                Fields.account: account,
            }
        )
        await client_failed.send_request(
            payload={
                Fields.command: Commands.register,
                Fields.account: account
            }
        )
        await client_failed.close()
        fake_set_payload = make_fake()
        with patch("cookieserver.src.storage.Account.set_payload", new=fake_set_payload):
            response = await async_client.send_request(
                payload={
                    Fields.command: Commands.set,
                    Fields.account: account,
                    Fields.payload: cookies_not_sample,
                }
            )
        # сет успешный, провал одного аккаунта не должен влиять на результат
        assert response[Fields.result]
        assert server.storage.get_account(account).payload == cookies_not_sample

# todo: написать тест на проверку лока
