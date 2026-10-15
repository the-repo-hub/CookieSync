import asyncio
import json
import logging
from abc import ABC, abstractmethod
from functools import partial
from typing import Dict, Type

from cookieserver.src.choices import Commands, Fields
from cookieserver.src.request import Request
from cookieserver.src.errors import HandleCommandError
from cookieserver.src.settings import BROADCAST_TIMEOUT
from cookieserver.src.storage import AccountStorage, run_storage_write
from websockets.asyncio.server import ServerConnection

logger = logging.getLogger(__name__)

class Command(ABC):

    @abstractmethod
    async def execute(self, storage: AccountStorage, request: Request, websocket: ServerConnection) -> Dict:
        pass

COMMAND_REGISTRY: Dict[str, Type[Command]] = {}

def register_command(name: str):
    def wrapper(cls: Type[Command]):
        COMMAND_REGISTRY[name] = cls
        return cls
    return wrapper

@register_command(Commands.register)
class RegisterCookiesCommand(Command):

    async def execute(self, storage: AccountStorage, request: Request, websocket: ServerConnection) -> Dict:
        account = await storage.get_or_create_account(request.account)
        async with account.lock:
            storage.add_client(websocket, account.name)
            logger.info(f"Client {websocket.remote_address} registered in account {account.name}")
            return {
                Fields.message: f'Registered successfully in account {account.name}.',
                Fields.payload: account.payload,
                Fields.revision: account.revision,
                Fields.retry_after: account.retry_after(),
            }

@register_command(Commands.set)
class SetCookiesCommand(Command):

    async def execute(self, storage: AccountStorage, request: Request, websocket: ServerConnection) -> Dict:
        return await self._execute_update(storage, request, websocket)

    async def _execute_update(
        self, storage: AccountStorage, request: Request, websocket: ServerConnection,
        expected_revision: int | None = None,
    ) -> Dict:
        account = storage.require_account(request.account)
        async with account.lock:
            storage.require_registered_client(websocket, request.account)
            update = await run_storage_write(
                partial(
                    storage.set_cookies, request.account, request.payload,
                    expected_revision=expected_revision,
                )
            )
            output = {
                Fields.command: Commands.set,
                Fields.payload: account.payload,
                Fields.revision: account.revision,
                Fields.retry_after: update.retry_after,
            }
            if update.changed:
                websockets = storage.websockets_by_account.get(request.account, set())
                tasks = [asyncio.create_task(self._send(ws, output))
                         for ws in websockets if ws is not websocket]
                await asyncio.gather(*tasks)
            logger.debug(f"Client {websocket.remote_address} has set_cookies done in {account.name}")
            return {
                Fields.message: (
                    'Cookies were set successfully'
                    if update.accepted
                    else 'Account revision changed; stored cookies restored'
                    if expected_revision is not None
                    else f'Cookie update blocked for {update.retry_after}s; stored cookies restored'
                ),
                Fields.payload: account.payload,
                Fields.accepted: update.accepted,
                Fields.revision: account.revision,
                Fields.retry_after: update.retry_after,
            }

    async def _send(self, websocket: ServerConnection, output: Dict):
        try:
            await asyncio.wait_for(
                websocket.send(json.dumps(output)),
                timeout=BROADCAST_TIMEOUT,
            )
        except Exception:
            logger.exception(f'Failed to send cookies to {websocket.remote_address}')
            try:
                await websocket.close(
                    code=1011,
                    reason='Cookie synchronization failed',
                )
            except Exception:
                logger.exception(
                    f'Failed to close stale client {websocket.remote_address}'
                )


@register_command(Commands.refresh)
class RefreshCookiesCommand(SetCookiesCommand):
    """Compare-and-swap replacement after a client observes a fresh login."""

    async def execute(self, storage: AccountStorage, request: Request, websocket: ServerConnection) -> Dict:
        if type(request.expected_revision) is not int or request.expected_revision < 0:
            raise HandleCommandError('refresh requires a non-negative integer expected_revision')
        return await self._execute_update(storage, request, websocket, request.expected_revision)
