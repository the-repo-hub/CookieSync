"""Test module for CookieServer."""
import asyncio
import json
import os
import uuid
from threading import Thread
from typing import Dict
from unittest import mock

import pytest

from cookieserver.src.choices import Fields, Commands
from cookieserver.src.client import Client
from cookieserver.src.server import Server
from cookieserver.src.settings import ACCOUNTS_PATH, COOKIE_SERVER_PATH
import pytest_asyncio

SERVER_ADDRESS = '0.0.0.0'
SERVER_PORT = 52314

@pytest.fixture(scope='class')
def cookies():
    with open(os.path.join(COOKIE_SERVER_PATH, "tests/test_cookie.json")) as f:
        yield json.loads(f.read())

@pytest.fixture(scope="class")
def server():
    """Server fixture."""
    srv = Server(SERVER_ADDRESS, SERVER_PORT)
    Thread(target=srv.start).start()
    yield srv
    srv.stop()

@pytest.fixture
def not_storage_account(server):
    account = 'test_to_create'
    yield account
    try:
        server._cookie_storage.remove_file(account)
    except Exception:
        pass

@pytest.fixture
def account(server, cookies):
    test_account = 'test_account'
    if test_account in server._cookie_storage.get_all_accounts():
        server._cookie_storage.remove_file(test_account)
    server._cookie_storage.add_file(test_account)
    yield test_account
    try:
        server._cookie_storage.remove_file(test_account)
    except Exception:
        pass

@pytest_asyncio.fixture
async def async_client(server):
    """Async client fixture."""
    client = AsyncClient('test_client')
    await client.connect(SERVER_ADDRESS, SERVER_PORT)
    yield client
    await client.close()


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
        self.reader, self.writer = await asyncio.open_connection(host, port)
        self.listen_task = asyncio.create_task(self.listen())

    async def send_request(self, payload: Dict, timeout=10):
        request_id = payload[Fields.request_id]
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

    @pytest.mark.asyncio
    async def test_get_all(self, server, async_client):
        """Test get_all command"""
        payload = {
            Fields.request_id: str(uuid.uuid4()),
            Fields.command: Commands.get_all
        }
        response = await async_client.send_request(payload)
        assert response[Fields.result]
        assert response[Fields.message] == server._cookie_storage.get_all_accounts()
        assert response[Fields.message] == [acc.split('.')[0] for acc in os.listdir(ACCOUNTS_PATH)]

    @pytest.mark.asyncio
    async def test_account_creation(self, server, not_storage_account, async_client):

        payload = {
            Fields.request_id: str(uuid.uuid4()),
            Fields.command: Commands.create,
            Fields.hash: not_storage_account,
        }
        response = await async_client.send_request(payload)
        assert response[Fields.result]
        assert not_storage_account in [acc.split('.')[0] for acc in os.listdir(ACCOUNTS_PATH)]
        assert not_storage_account in server._cookie_storage.get_all_accounts()

    @pytest.mark.asyncio
    async def test_account_removing(self, server, account, async_client):
        payload = {
            Fields.request_id: str(uuid.uuid4()),
            Fields.command: Commands.delete,
            Fields.hash: account,
        }
        response = await async_client.send_request(payload)
        assert response[Fields.result]
        assert account not in [acc.split('.')[0] for acc in os.listdir(ACCOUNTS_PATH)]
        assert account not in server._cookie_storage.get_all_accounts()

    @pytest.mark.asyncio
    async def test_register(self, server, account, async_client):
        payload = {
            Fields.request_id: str(uuid.uuid4()),
            Fields.command: Commands.register,
            Fields.hash: account,
        }
        response = await async_client.send_request(payload)
        assert response[Fields.result]
        assert Client.registered_clients.get(account)

    @pytest.mark.asyncio
    async def test_register_failed(self, server, async_client, not_storage_account):
        #there is no that cookie on server, so server cant do it
        payload = {
            Fields.request_id: str(uuid.uuid4()),
            Fields.command: Commands.register,
            Fields.hash: not_storage_account,
        }
        response = await async_client.send_request(payload)
        assert not response[Fields.result]
        assert not Client.registered_clients.get(not_storage_account)

    @pytest.mark.asyncio
    async def test_delete_failed(self, server, async_client, not_storage_account):
        #nothing to delete
        payload = {
            Fields.request_id: str(uuid.uuid4()),
            Fields.command: Commands.delete,
            Fields.hash: not_storage_account,
        }
        response = await async_client.send_request(payload)
        assert not response[Fields.result]
        assert not Client.registered_clients.get(not_storage_account)

    @pytest.mark.asyncio
    @mock.patch('cookieserver.src.storage.CookieStorage._do_all_checks', return_value=None)
    async def test_set(self, mock_do_all_checks, server, cookies, account, async_client):
        """Simple set"""

        client_conn_2 = AsyncClient('client_2')
        # включаем листенеры
        await client_conn_2.connect(SERVER_ADDRESS, SERVER_PORT)
        await async_client.send_request(
            payload={
                Fields.request_id: str(uuid.uuid4()),
                Fields.command: Commands.register,
                Fields.hash: account,
            }
        )

        await client_conn_2.send_request(
            payload={
                Fields.request_id: str(uuid.uuid4()),
                Fields.command: Commands.register,
                Fields.hash: account
            }
        )
        async_client.cookies = cookies
        assert not client_conn_2.cookies
        response = await async_client.send_request(
            payload={
                Fields.request_id: str(uuid.uuid4()),
                Fields.command: Commands.set,
                Fields.hash: account,
                Fields.payload: cookies,
            }
        )
        # проверки на то, что обычное изменение кук работает
        assert response[Fields.result]
        assert server._cookie_storage.get_cookies(account) == cookies
        assert account in [acc.split('.')[0] for acc in os.listdir(ACCOUNTS_PATH)]

        # проверки на то, что сервер отправил куки и они были корректно приняты
        assert client_conn_2.cookies
        assert async_client.cookies == client_conn_2.cookies
        await client_conn_2.close()

    @pytest.mark.asyncio
    @mock.patch('cookieserver.src.storage.CookieStorage._do_all_checks', return_value=None)
    async def test_set_failed(self, mock, server, cookies, async_client, account):
        """Тест на падение одного из клиентов"""
        client_failed = AsyncClient('client_failed')
        await client_failed.connect(SERVER_ADDRESS, SERVER_PORT)
        await async_client.send_request(
            payload={
                Fields.request_id: str(uuid.uuid4()),
                Fields.command: Commands.register,
                Fields.hash: account,
            }
        )

        await client_failed.send_request(
            payload={
                Fields.request_id: str(uuid.uuid4()),
                Fields.command: Commands.register,
                Fields.hash: account
            }
        )
        await client_failed.close()
        async_client.cookies = cookies
        response = await async_client.send_request(
            payload={
                Fields.request_id: str(uuid.uuid4()),
                Fields.command: Commands.set,
                Fields.hash: account,
                Fields.payload: cookies,
            }
        )

        assert response[Fields.result]
        assert server._cookie_storage.get_cookies(account) == cookies
        # на всякий случай
        assert not client_failed.cookies
