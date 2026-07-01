import asyncio
import json
import logging
from abc import ABC, abstractmethod
from typing import Dict, Type

from cookieserver.src.choices import Commands, Fields
from cookieserver.src.request import Request
from cookieserver.src.settings import ENCODING
from cookieserver.src.storage import AccountStorage
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
        account = storage.require_account(request.account)
        async with account.lock:
            storage.websockets_by_account.setdefault(account.name, set()).add(websocket)
            websocket.logger.info(f"Client {websocket.remote_address} successfully registered in {account.name}")
            return {
                Fields.message: f'You was registered successfully in account {account.name}.',
                Fields.payload: account.payload,
            }

@register_command(Commands.set)
class SetCookiesCommand(Command):

    async def execute(self, storage: AccountStorage, request: Request, websocket: ServerConnection) -> Dict:

        account = storage.require_account(request.account)
        async with account.lock:
            storage.set_cookies(request.account, request)
            output = {
                Fields.command: Commands.set,
                Fields.payload: request.payload,
            }
            websockets = storage.websockets_by_account.get(request.account)
            tasks = [asyncio.create_task(self._send(ws, output))
                     for ws in websockets if ws is not websocket]
            await asyncio.gather(*tasks)
            logger.debug(f"Client {websocket.remote_address} has set_cookies done in {account.name}")
            return {
                Fields.message: 'Cookies was set successfully',
            }

    async def _send(self, websocket: ServerConnection, output: Dict):
        try:
            encoded = json.dumps(output).encode(ENCODING)
            await websocket.send(encoded)
        except Exception:
            pass
