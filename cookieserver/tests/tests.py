"""Test module for CookieServer."""
import asyncio
import json
import os
import ssl
import threading
import uuid
from typing import Dict
from unittest.mock import patch, AsyncMock

import pytest
import pytest_asyncio

from cookieserver.src.choices import Commands, Fields
from cookieserver.src.server import Server
from cookieserver.src.settings import ACCOUNTS_PATH, COOKIE_SERVER_PATH
import time
from functools import partial

SERVER_ADDRESS = '127.0.0.1'
SERVER_PORT = 52314

@pytest.fixture(scope='class')
def cookies():
    with open(os.path.join(COOKIE_SERVER_PATH, "tests/test_cookie.json")) as f:
        yield json.loads(f.read())

@pytest_asyncio.fixture(scope="class")
async def server():

    server = Server(SERVER_ADDRESS, SERVER_PORT)
    t = threading.Thread(target=server.start_sync)
    t.start()
    yield server
    server.stop_sync()
    t.join()

@pytest.fixture
def not_storage_account(server):
    account = 'test_to_create'
    yield account
    try:
        server.account_storage.remove_account(account)
    except Exception:
        pass

@pytest.fixture
def account(server, cookies):
    test_account_name = 'test_account'
    if test_account_name in server.account_storage.get_all_accounts():
        server.account_storage.remove_account(test_account_name)
    server.account_storage.add_account(test_account_name)
    yield test_account_name
    try:
        server.account_storage.remove_account(test_account_name)
    except Exception:
        pass

@pytest_asyncio.fixture
async def async_client(server):
    """Async client fixture."""
    client = AsyncClient('test_client')
    await client.connect(SERVER_ADDRESS, SERVER_PORT)
    yield client
    await client.close()

def make_fake(wait=0):
    def fake(self, payload):
        import time
        time.sleep(wait)
        self.payload = payload
        self.updated_at = 0
        self.write_file()
    return fake

class AsyncClient:
    def __init__(self, identifier: str):
        self.reader = None
        self.writer = None
        self.listen_task = None
        self.identifier = identifier
        self.pending = {}
        self.command_handlers = {}
        self.cookies = {}

    async def connect(self, host, port):
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        self.reader, self.writer = await asyncio.open_connection(host, port)
        self.listen_task = asyncio.create_task(self.listen())

    async def send_request(self, payload: Dict, timeout=10):
        request_id = str(uuid.uuid4())
        payload[Fields.request_id] = request_id
        encoded = json.dumps(payload).encode()
        length_prefix = len(encoded).to_bytes(4, "big")
        future = asyncio.get_running_loop().create_future()
        self.pending[request_id] = future

        # отправляем
        self.writer.write(length_prefix + encoded)
        await self.writer.drain()
        try:
            return await asyncio.wait_for(future, timeout)
        finally:
            self.pending.pop(request_id, None)

    # -------------------------
    # Listener
    # -------------------------
    async def listen(self):
        try:
            while True:
                # читаем 4 байта длины
                raw_length = await self.reader.readexactly(4)
                length = int.from_bytes(raw_length, "big")

                # читаем тело
                body = await self.reader.readexactly(length)
                response = json.loads(body.decode())
                await self.route_response(response)

        except asyncio.IncompleteReadError:
            print("Connection closed by server")

    # -------------------------
    # Маршрутизация
    # -------------------------
    async def route_response(self, response):
        request_id = response[Fields.request_id]
        if future := self.pending.get(request_id):
            if not future.done():
                future.set_result(response)
        else:
            command = response.get("command")
            if command == Commands.set:
                # we dont need complex functionality
                self.cookies = response.get("payload")

    async def close(self):
        self.listen_task.cancel()
        try:
            await self.listen_task  # дождаться завершения
        except asyncio.CancelledError:
            pass
        if self.writer:
            self.writer.close()
            await self.writer.wait_closed()

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
        assert server.clients_by_account.get(account)
        assert response[Fields.payload] == server.account_storage.get_account(account).payload

        # закрываем соединение, в это время сервер должен выкинуть клиента из списка
        await async_client.close()
        await self.wait_until(lambda: not server.clients_by_account.get(account))

    @pytest.mark.asyncio
    async def test_register_failed(self, server, async_client, not_storage_account):
        #there is no that cookie on server, so server cant do it
        payload = {
            Fields.command: Commands.register,
            Fields.account: not_storage_account,
        }
        response = await async_client.send_request(payload)
        assert not response[Fields.result]
        assert not server.clients_by_account.get(not_storage_account)

    @pytest.mark.asyncio
    async def test_set(self, server, cookies, account, async_client):
        """Simple set"""

        client_conn_2 = AsyncClient('client_2')
        # включаем листенер
        await client_conn_2.connect(SERVER_ADDRESS, SERVER_PORT)
        await async_client.send_request(
            payload={
                Fields.command: Commands.register,
                Fields.account: account,
            }
        )

        await client_conn_2.send_request(
            payload={
                Fields.command: Commands.register,
                Fields.account: account
            }
        )
        async_client.cookies = cookies
        assert not client_conn_2.cookies
        fake_set_payload = make_fake()
        with patch("cookieserver.src.storage.Account.set_payload", new=fake_set_payload):
            response = await async_client.send_request(
                payload={
                    Fields.command: Commands.set,
                    Fields.account: account,
                    Fields.payload: cookies,
                }
            )
        assert len(server.clients_by_account.get(account)) == 2
        assert response[Fields.result] is True
        # проверки на то, что обычное изменение кук работает
        assert response[Fields.result]
        assert server.account_storage.get_account(account).payload == cookies
        assert account in [acc.split('.')[0] for acc in os.listdir(ACCOUNTS_PATH)]

        # проверки на то, что сервер отправил куки и они были корректно приняты

        await self.wait_until(lambda: client_conn_2.cookies)
        assert async_client.cookies == client_conn_2.cookies
        await client_conn_2.close()

    @pytest.mark.asyncio
    async def test_set_failed(self, server, cookies, async_client, account):
        """Тест на падение одного из клиентов"""
        client_failed = AsyncClient('client_failed')
        await client_failed.connect(SERVER_ADDRESS, SERVER_PORT)
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
                    Fields.payload: cookies,
                }
            )
        # сет успешный, провал одного аккаунта не должен влиять на результат
        assert response[Fields.result]
        assert server.account_storage.get_account(account).payload == cookies
        # на всякий случай
        assert not client_failed.cookies

    @patch("cookieserver.src.storage.Account.set_payload", new=make_fake(3))
    @pytest.mark.asyncio
    async def test_long_set(self, server, cookies, async_client, account):
        await async_client.send_request({
            Fields.command: Commands.register,
            Fields.account: account,
        })

        client_locked = AsyncClient('client_locked')
        await client_locked.connect(SERVER_ADDRESS, SERVER_PORT)

        # задача, которая залочит аккаунт на 3 секунды
        task_set = asyncio.create_task(async_client.send_request({
            Fields.command: Commands.set,
            Fields.account: account,
            Fields.payload: cookies,
        }))
        await asyncio.sleep(0.2)  # даём взять lock

        # клиент пытается зарегистрировать залоченый аккаунт, лок сета должен его задержать
        task_reg = asyncio.create_task(client_locked.send_request({
            Fields.command: Commands.register,
            Fields.account: account,
        }))

        await asyncio.sleep(0.2) # даём взять lock
        assert not task_reg.done()
        assert not task_set.done()
        await task_set
        await task_reg
