import asyncio
import json
import logging
from abc import ABC, abstractmethod
from typing import Dict, Type

from cookieserver.src.choices import Commands, Fields
from cookieserver.src.client import Client
from cookieserver.src.request import Request
from cookieserver.src.settings import ENCODING
from cookieserver.src.storage import AccountStorage

logger = logging.getLogger(__name__)

class Command(ABC):

    @abstractmethod
    async def execute(self, storage: AccountStorage, request: Request) -> Dict:
        pass

COMMAND_REGISTRY: Dict[str, Type[Command]] = {}

def register_command(name: str):
    def wrapper(cls: Type[Command]):
        COMMAND_REGISTRY[name] = cls
        return cls
    return wrapper

@register_command(Commands.register)
class RegisterCookiesCommand(Command):

    async def execute(self, storage: AccountStorage, request: Request) -> Dict:
        account = storage.require_account(request.account)
        async with account.lock:
            storage.clients_by_account.setdefault(account.name, set()).add(request.client)
            logger.info(f"Client {request.client.full_address} successfully registered in {account.name}")
            return {
                Fields.message: f'You was registered successfully in account {account.name}.',
                Fields.payload: account.payload,
            }

@register_command(Commands.set)
class SetCookiesCommand(Command):

    async def execute(self, storage: AccountStorage, request: Request) -> Dict:

        account = storage.require_account(request.account)
        async with account.lock:
            storage.set_cookies(request.account, request.payload)
            output = {
                Fields.request_id: request.request_id,
                Fields.command: Commands.set,
                Fields.payload: request.payload,
            }
            clients = storage.clients_by_account.get(request.account)
            tasks = [asyncio.create_task(self._send(client, output))
                     for client in clients if client.writer is not request.client.writer]
            await asyncio.gather(*tasks)
            logger.debug(f"Client {request.client.full_address} has set_cookies done in {account.name}")
            return {
                Fields.message: 'Cookies was set successfully',
            }

    async def _send(self, client: Client, output: Dict):
        try:
            encoded = json.dumps(output).encode(ENCODING)
            length_prefix = len(encoded).to_bytes(4, "big")
            client.writer.write(length_prefix + encoded)
            await client.writer.drain()
        except Exception:
            pass
