import asyncio
import json
import logging
import os
import ssl
from typing import Dict, Optional, Set

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

PING_INTERVAL = 30
PING_TIMEOUT = 10


class Server:

    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
        self.server: asyncio.AbstractServer | None = None
        self.storage = AccountStorage()
        self._ws_accounts: Dict[ServerConnection, str] = {}

    def _track_ws(self, websocket: ServerConnection, account_name: str) -> None:
        self._ws_accounts[websocket] = account_name

    def _untrack_ws(self, websocket: ServerConnection) -> Optional[str]:
        return self._ws_accounts.pop(websocket, None)

    async def _connection_processor(self, websocket: ServerConnection):
        logger.info(f"Client connected: {websocket.remote_address}")
        try:
            async for message in websocket:
                try:
                    raw_data = json.loads(message)

                    if raw_data.get(Fields.command) == 'ping':
                        await websocket.send(json.dumps({
                            Fields.command: 'pong',
                            Fields.uuid: raw_data.get(Fields.uuid, '')
                        }))
                        continue

                    request = Request(raw_data)
                    logger.info(
                        f"Client {websocket.remote_address} sent command "
                        f"{request.command} to account {request.account}"
                    )

                    command_class = COMMAND_REGISTRY.get(request.command)
                    if not command_class:
                        raise HandleCommandError(f"Command '{request.command}' does not exist")

                    response = await command_class().execute(
                        storage=self.storage,
                        request=request,
                        websocket=websocket,
                    )
                    response.update({
                        Fields.result: True,
                        Fields.uuid: request.uuid
                    })

                    if request.command == 'register':
                        self._track_ws(websocket, request.account)

                    await websocket.send(json.dumps(response))

                except Exception as e:
                    logger.exception(f"Error processing message: {e}")
                    uuid = ''
                    if 'request' in dir() and request:
                        uuid = getattr(request, 'uuid', '')
                    error_response = {
                        Fields.result: False,
                        Fields.message: str(e),
                        Fields.uuid: uuid,
                    }
                    await websocket.send(json.dumps(error_response))
        finally:
            account_name = self._untrack_ws(websocket)
            if account_name:
                ws_set = self.storage.websockets_by_account.get(account_name)
                if ws_set:
                    ws_set.discard(websocket)
                    logger.info(
                        f"Client {websocket.remote_address} removed from account {account_name}"
                    )
            logger.info(f"Client disconnected: {websocket.remote_address}")

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
            ssl=context,
            ping_interval=PING_INTERVAL,
            ping_timeout=PING_TIMEOUT,
        )

    async def stop(self):
        logger.info("Stopping server...")

        if not self.server:
            return

        self.server.close()
        await self.server.wait_closed()
        logger.info("Server stopped")
