import asyncio
import json
import logging
import ssl
import uuid
from typing import Any

import websockets
from websockets.exceptions import ConnectionClosed

from cookieserver.src.choices import Fields

logger = logging.getLogger(__name__)


class AsyncWSClient:
    def __init__(self, name: str):
        self.name = name
        self.ws = None

        self._listen_task: asyncio.Task | None = None

        # uuid -> Future
        self._pending: dict[str, asyncio.Future] = {}

        # Сообщения, которые сервер прислал сам: broadcast, set cookies и т.д.
        self.server_messages: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

        self.last_request_uuid: str | None = None

    async def connect(self, url: str):
        ssl_context = None

        if url.startswith("wss://"):
            ssl_context = ssl._create_unverified_context()

        self.ws = await websockets.connect(url, ssl=ssl_context)
        self._listen_task = asyncio.create_task(self._listen())

    async def _listen(self):
        try:
            async for message in self.ws:
                data = json.loads(message)

                request_uuid = data.get(Fields.uuid)

                if request_uuid and request_uuid in self._pending:
                    future = self._pending[request_uuid]

                    if not future.done():
                        future.set_result(data)
                else:
                    await self.server_messages.put(data)

        except ConnectionClosed as e:
            logger.info("Client %s websocket closed", self.name)
            self._fail_pending(e)

        except Exception as e:
            logger.exception("Client %s listener failed", self.name)
            self._fail_pending(e)

    def _fail_pending(self, exc: BaseException):
        for future in self._pending.values():
            if not future.done():
                future.set_exception(exc)

        self._pending.clear()

    async def send_request(
        self,
        payload: dict[str, Any],
        timeout: float = 5,
    ) -> dict[str, Any]:
        if self.ws is None:
            raise RuntimeError("WebSocket is not connected")

        request_uuid = str(uuid.uuid4())
        self.last_request_uuid = request_uuid

        payload = {
            **payload,
            Fields.uuid: request_uuid,
        }

        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self._pending[request_uuid] = future

        try:
            await self.ws.send(json.dumps(payload))

            return await asyncio.wait_for(
                future,
                timeout=timeout,
            )

        except asyncio.TimeoutError:
            raise TimeoutError(
                f"Server didn't respond to request uuid={request_uuid}"
            )

        finally:
            self._pending.pop(request_uuid, None)

    async def send_raw(self, text: str) -> None:
        """Отправляет произвольный (возможно, битый) текст прямо в сокет.

        Ответ на битый запрос сервер шлёт с пустым uuid, поэтому он не
        коррелируется через _pending, а попадает в server_messages.
        """
        if self.ws is None:
            raise RuntimeError("WebSocket is not connected")
        await self.ws.send(text)

    async def recv_server_message(self, timeout: float = 5) -> dict[str, Any]:
        return await asyncio.wait_for(
            self.server_messages.get(),
            timeout=timeout,
        )

    async def close(self):
        if self.ws is not None:
            await self.ws.close()
            self.ws = None

        if self._listen_task is not None:
            self._listen_task.cancel()

            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass

            self._listen_task = None

        self._fail_pending(ConnectionError("Client closed"))
