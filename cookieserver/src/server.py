import asyncio
import json
import logging
import os
import ssl

import websockets
from websockets.asyncio.server import Server as WSServer, ServerConnection

from cookieserver.src.choices import Fields
from cookieserver.src.commands import COMMAND_REGISTRY
from cookieserver.src.errors import HandleCommandError, StorageError
from cookieserver.src.request import Request
from cookieserver.src.settings import KEYS_PATH, PING_INTERVAL, PING_TIMEOUT
from cookieserver.src.storage import AccountStorage

logger = logging.getLogger(__name__)


class Server:

    def __init__(self, host: str, port: int, use_tls: bool = True):
        self.host = host
        self.port = port
        self.use_tls = use_tls
        self.server: WSServer | None = None
        self.storage = AccountStorage()

    async def _connection_processor(self, websocket: ServerConnection) -> None:
        logger.info(f"Client connected: {websocket.remote_address}")
        try:
            async for message in websocket:
                await self._handle_message(websocket, message)
        finally:
            self.storage.remove_client(websocket)
            logger.info(f"Client disconnected: {websocket.remote_address}")

    async def _handle_message(
        self,
        websocket: ServerConnection,
        message: str,
    ) -> None:
        request_uuid = ''
        try:
            raw_data = json.loads(message)
            if not isinstance(raw_data, dict):
                raise ValueError('Message must be a JSON object')
            request_uuid = raw_data.get(Fields.uuid, '')
        except (json.JSONDecodeError, TypeError, ValueError) as e:
            logger.warning(f"Malformed message from {websocket.remote_address}: {e} {message}")
            await websocket.send(json.dumps({
                Fields.result: False,
                Fields.message: 'Invalid message format',
                Fields.uuid: request_uuid,
            }))
            return

        try:
            request = Request(raw_data)
            logger.info(
                f"Received command {request.command} from "
                f"client {websocket.remote_address} for account {request.account}"
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

            await websocket.send(json.dumps(response))

        except HandleCommandError as e:
            logger.warning(f"Protocol error from {websocket.remote_address}: {e}")
            logger.debug(f"Failed message from {websocket.remote_address}: {message!r}")
            await websocket.send(json.dumps({
                Fields.result: False,
                Fields.message: str(e),
                Fields.uuid: request_uuid,
            }))
        except StorageError as e:
            logger.warning(f"Storage error from {websocket.remote_address}: {e}")
            logger.debug(f"Failed message from {websocket.remote_address}: {message!r}")
            await websocket.send(json.dumps({
                Fields.result: False,
                Fields.message: str(e),
                Fields.uuid: request_uuid,
            }))
        except Exception:
            logger.exception("Unexpected error processing message")
            logger.debug(f"Failing message from {websocket.remote_address}: {message!r}")
            await websocket.send(json.dumps({
                Fields.result: False,
                Fields.message: 'Internal server error',
                Fields.uuid: request_uuid,
            }))

    async def start(self) -> None:
        ssl_context = None
        if self.use_tls:
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(
                certfile=os.path.join(KEYS_PATH, "cert.pem"),
                keyfile=os.path.join(KEYS_PATH, "key.pem"),
            )
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            ssl_context = context

        self.server = await websockets.serve(
            self._connection_processor,
            self.host,
            self.port,
            ssl=ssl_context,
            ping_interval=PING_INTERVAL,
            ping_timeout=PING_TIMEOUT,
        )

    async def wait_closed(self) -> None:
        if self.server:
            await self.server.wait_closed()

    async def run(self) -> None:
        await self.start()
        try:
            await self.wait_closed()
        except asyncio.CancelledError:
            pass
        finally:
            await self.stop()

    async def stop(self) -> None:

        if not self.server:
            return

        self.server.close()
        await self.server.wait_closed()
