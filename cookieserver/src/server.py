import asyncio
import json
import logging
import os
import ssl
from typing import Dict, Set

import websockets
from websockets.asyncio.server import ServerConnection

from cookieserver.src.choices import Fields
from cookieserver.src.commands import COMMAND_REGISTRY
from cookieserver.src.errors import HandleCommandError
from cookieserver.src.request import Request
from cookieserver.src.settings import KEYS_PATH
from cookieserver.src.storage import AccountStorage
from uuid import uuid4

logger = logging.getLogger(__name__)

class Server:

    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
        self.server: asyncio.AbstractServer | None = None
        self.storage = AccountStorage()

    async def _connection_processor(self, websocket: ServerConnection):
        """
        Handle a client connection.
        """
        logger.info(f"Client connected: {websocket.remote_address}")
        request = False
        # message is str
        async for message in websocket:
            # проверяем валидность сообщения
            try:
                raw_data = json.loads(message)
                request = Request(raw_data)
                logger.info(
                    f"Client {websocket.remote_address} successfully sent proper request to {request.account} with command {request.command}"
                )
                command_class = COMMAND_REGISTRY.get(request.command)
                if not command_class:
                    raise HandleCommandError("Command does not exist")
                response = await command_class().execute(
                    storage=self.storage,
                    request=request,
                    websocket=websocket,
                )
                response.update({
                    Fields.result: True,
                    Fields.uuid: request.uuid
                })
                await websocket.send(json.dumps(response))
            except Exception as e:
                logger.exception(f"Error occurred {e.__class__}: {e}")
                error_response = {
                    Fields.result: False,
                    Fields.message: str(e),
                    Fields.uuid: request.uuid,
                }
                encoded = json.dumps(error_response).encode()
                await websocket.send(encoded)
        # если клиент закрыл соединение,
        if request and (websockets_set := self.storage.websockets_by_account.get(request.account)):
            websockets_set.discard(websocket)

    async def start(self):
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(
            certfile=os.path.join(KEYS_PATH, "cert.pem"),
            keyfile=os.path.join(KEYS_PATH, "key.pem"),
        )
        context.minimum_version = ssl.TLSVersion.TLSv1_2

        self.server = await websockets.serve(
            self._connection_processor,
            self.host,
            self.port,
            ssl=context
        )

    async def stop(self):
        logger.info("Stopping server...")

        if not self.server:
            return

        self.server.close()
        await self.server.wait_closed()
        logger.info("Server stopped")
