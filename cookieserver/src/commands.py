import asyncio
import json
import logging
from abc import ABC, abstractmethod
from typing import Dict, Type

from cookieserver.src.choices import Commands, Fields
from cookieserver.src.client import Client
from cookieserver.src.message import Message
from cookieserver.src.settings import SERVER_LOGGER, ENCODING
from cookieserver.src.storage import AccountStorage

logger = logging.getLogger(__name__)

class Command(ABC):

    @abstractmethod
    def execute(self, storage: AccountStorage, message: Message, client: Client) -> Dict:
        pass

COMMAND_REGISTRY: Dict[str, Type[Command]] = {}

def register_command(name: str):
    def wrapper(cls: Type[Command]):
        COMMAND_REGISTRY[name] = cls
        return cls
    return wrapper

# todo
# i have to add AdminCommand entity
class GetAllAccountsCommand(Command):

    def execute(self, storage: AccountStorage, message: Message, client: Client) -> Dict:

        logger.info(f'Client {client.full_address} got all accounts')
        return {
            Fields.message: storage.get_all_accounts(),
        }

@register_command(Commands.create)
class CreateCookiesCommand(Command):

    def execute(self, storage: AccountStorage, message: Message, client: Client) -> Dict:
        storage.add_account(message.account)
        return {
            Fields.message: 'Cookies was created successfully',
        }

@register_command(Commands.delete)
class DeleteCommand(Command):

    def execute(self, storage: AccountStorage, message: Message, client: Client) -> Dict:
        storage.remove_account(message.account)
        # todo прописать логику отключения клиентов
        SERVER_LOGGER.info(f'Client {client.full_address} successfully executed {Commands.delete} command. Cookies {message.account} removed')
        result = {
            Fields.message: f'Account {message.account} was removed successfully',
        }
        return result

@register_command(Commands.set)
class SetCookiesCommand(Command):

    def execute(self, storage: AccountStorage, message: Message, client: Client) -> Dict:

        # todo
        # добавить лок на аккаунт
        storage.set_cookies(message.account, message.payload)
        loop = asyncio.get_running_loop()
        for c in storage.get_clients_by_account(message.account):
            if c.writer is client.writer:
                continue
            output = {
                Fields.request_id: message.request_id,
                Fields.command: Commands.set,
                Fields.payload: message.payload,
            }
            request = json.dumps(output).encode(ENCODING)
            loop.create_task(self._send(c.writer, request))
        return {
            Fields.message: 'Cookies was set successfully',
        }

    async def _send(self, writer, data):
        try:
            length_prefix = len(data).to_bytes(4, "big")
            writer.write(length_prefix + data)
            await writer.drain()
        except Exception:
            # перехватываем исключение, чтобы продолжить отправлять и другим клиентам
            pass

@register_command(Commands.get)
class GetCookiesCommand(Command):

    def execute(self, storage: AccountStorage, message: Message, client: Client) -> Dict:
        payload = storage.require_account(message.account).get_payload()
        return {
            Fields.message: 'Cookies was retrieved successfully',
            Fields.payload: payload,
        }
