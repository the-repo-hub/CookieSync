import asyncio
import json
import logging
import os
import ssl
from asyncio import StreamReader, StreamWriter
from typing import Dict, Set
from urllib.request import Request

from cookieserver.src.choices import Fields
from cookieserver.src.client import Client
from cookieserver.src.commands import COMMAND_REGISTRY
from cookieserver.src.errors import HandleCommandError
from cookieserver.src.request import Request
from cookieserver.src.settings import KEYS_PATH, MAX_SIZE
from cookieserver.src.storage import AccountStorage

logger = logging.getLogger(__name__)

class Server:

    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
        self.server: asyncio.AbstractServer | None = None
        # {account_name: set(client, client2)}
        # аккаунт
        self.clients_by_account: Dict[str, Set[Client]] = {}
        self.account_storage = AccountStorage(self.clients_by_account)

    async def _handle_client(self, reader: StreamReader, writer: StreamWriter):
        """
        Handle a client connection.
        """
        logger.info(f"Client connected: {writer.get_extra_info('peername')}")
        request = None
        try:
            while True:
                # читаем длину сообщения
                length_bytes = await reader.readexactly(4)
                length = int.from_bytes(length_bytes, "big")
                if length > MAX_SIZE:
                    raise HandleCommandError('Too big request')
                # читаем тело
                raw_data = await reader.readexactly(length)
                if not raw_data:
                    break

                # проверяем валидность сообщения
                raw_data = json.loads(raw_data.decode())
                client = Client(writer)
                request = Request(
                    raw_data=raw_data,
                    client=client
                )
                logger.info(
                    f"Client {client.full_address} successfully sent proper request to {request.account} with command {request.command}"
                )
                command_class = COMMAND_REGISTRY.get(request.command)
                if not command_class:
                    raise HandleCommandError("Command does not exist")
                response = await command_class().execute(
                    storage=self.account_storage,
                    request=request,
                )
                response.update({
                    Fields.result: True,
                    Fields.request_id: request.request_id,
                })
                encoded = json.dumps(response).encode()  # сериализуем в JSON
                length_prefix = len(encoded).to_bytes(4, "big")  # 4 байта длины, big-endian
                writer.write(length_prefix + encoded)  # сначала длина, потом данные
                await writer.drain()
        except Exception as e:
            logger.error(f"Error occurred {e.__class__}: {e}")
            error_response = {
                Fields.result: False,
                Fields.message: str(e),
            }
            if request:
                error_response[Fields.request_id] = request.request_id
            encoded = json.dumps(error_response).encode()
            length_prefix = len(encoded).to_bytes(4, "big")
            writer.write(length_prefix + encoded)  # сначала длина, потом данные
            await writer.drain()
        finally:
            if request and (clients := self.clients_by_account.get(request.account)):
                clients.discard(request.client)
            writer.close()
            await writer.wait_closed()

    async def start(self):
        logger.info(f"Starting server on {self.host}:{self.port} ...")
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(
            certfile=os.path.join(KEYS_PATH, "cert.pem"),
            keyfile=os.path.join(KEYS_PATH, "key.pem"),
        )
        context.check_hostname = False
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        self.server = await asyncio.start_server(
            self._handle_client,
            host=self.host,
            port=self.port,
            backlog=100,
            ssl=context,
        )
        logger.info(f"Server listening on {self.host}:{self.port}")
        await self.server.serve_forever()

    async def stop(self):
        logger.info("Server stopping...")

        if self.server:
            self.server.close()
            await self.server.wait_closed()

        # закрываем клиентов
        for clients_set in self.clients_by_account.values():
            for client in clients_set:
                client.writer.close()

        logger.info("Server stopped")
