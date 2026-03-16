import asyncio
import json
import logging
from abc import ABC, abstractmethod
from asyncio import StreamWriter
from typing import Dict, Type

from cookieserver.src.choices import Commands, Fields
from cookieserver.src.request import Request
from cookieserver.src.settings import ENCODING, SERVER_LOGGER
from cookieserver.src.storage import AccountStorage

logger = logging.getLogger(__name__)

class Command(ABC):

    @abstractmethod
    def execute(self, storage: AccountStorage, request: Request) -> Dict:
        pass

COMMAND_REGISTRY: Dict[str, Type[Command]] = {}

def register_command(name: str):
    def wrapper(cls: Type[Command]):
        COMMAND_REGISTRY[name] = cls
        return cls
    return wrapper

@register_command(Commands.create)
class CreateCookiesCommand(Command):

    def execute(self, storage: AccountStorage, request: Request) -> Dict:
        storage.add_account(request.account)
        return {
            Fields.message: 'Cookies was created successfully',
        }

@register_command(Commands.register)
class RegisterCookiesCommand(Command):

    def execute(self, storage: AccountStorage, request: Request) -> Dict:
        account = storage.require_account(request.account)
        storage.clients_by_account.setdefault(account.name, set()).add(request.client)
        return {
            Fields.message: 'Client was registered successfully',
        }

@register_command(Commands.delete)
class DeleteCommand(Command):

    def execute(self, storage: AccountStorage, request: Request) -> Dict:
        storage.remove_account(request.account)
        # todo прописать логику отключения клиентов
        SERVER_LOGGER.info(f'Client {request.client.full_address} successfully executed {Commands.delete} command. Cookies {request.account} removed')
        result = {
            Fields.message: f'Account {request.account} was removed successfully',
        }
        return result

@register_command(Commands.set)
class SetCookiesCommand(Command):

    def execute(self, storage: AccountStorage, request: Request) -> Dict:

        # todo
        # добавить лок на аккаунт
        storage.set_cookies(request.account, request.payload)
        loop = asyncio.get_running_loop()
        for c in storage.clients_by_account.get(request.account):
            if c.writer is request.client.writer:
                continue
            output = {
                Fields.request_id: request.request_id,
                Fields.command: Commands.set,
                Fields.payload: request.payload,
            }
            loop.create_task(self._send(c.writer, output))
        return {
            Fields.message: 'Cookies was set successfully',
        }

    async def _send(self, writer: StreamWriter, output: Dict) -> None:
        try:
            encoded = json.dumps(output).encode(ENCODING)
            length_prefix = len(encoded).to_bytes(4, "big")
            writer.write(length_prefix + encoded)
            await writer.drain()
        except Exception:
            # перехватываем исключение, чтобы продолжить отправлять и другим клиентам
            pass

@register_command(Commands.get)
class GetCookiesCommand(Command):

    def execute(self, storage: AccountStorage, request: Request) -> Dict:
        payload = storage.require_account(request.account).payload
        return {
            Fields.message: 'Cookies was retrieved successfully',
            Fields.payload: payload,
        }
