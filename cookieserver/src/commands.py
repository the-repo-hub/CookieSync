import json
from abc import ABC, abstractmethod
from typing import Dict, List

from cookieserver.src.choices import Commands, Fields
from cookieserver.src.client import Client, NoAccountException
from cookieserver.src.storage import CookieStorage, SetCookiesTimeoutError, AccountNotInStorageError, SameCookiesError, AccountAlreadyExists
from cookieserver.src.settings import SERVER_LOGGER, ENCODING


class Command(ABC):

    @abstractmethod
    def execute(self, storage: CookieStorage, client: Client, json_data: Dict) -> Dict:
        pass

class GetAllAccountsCommand(Command):

    def execute(self, storage: CookieStorage, client: Client, json_data: Dict) -> Dict:
        SERVER_LOGGER.info(f'Client {client.full_address} got all accounts')
        return {
            Fields.result: True,
            Fields.message: storage.get_all_accounts(),
        }

class CreateCookiesCommand(Command):

    def execute(self, storage: CookieStorage, client: Client, json_data: Dict) -> Dict:
        if not client.hash:
            SERVER_LOGGER.info(f'Client {client.full_address} does not sent a {Fields.hash}')
            return {
                Fields.result: False,
                Fields.message: f'You must send {Fields.hash}',
            }
        try:
            storage.add_file(client.hash)
        except AccountAlreadyExists:
            SERVER_LOGGER.info(f'Client {client.full_address} tried to create {client.hash} account, which already exists')
            return {
                Fields.result: False,
                Fields.message: f'Account {client.hash} already exists',
            }
        SERVER_LOGGER.info(f'Client {client.full_address} has created a {client.hash} account')
        return {
            Fields.result: True,
            Fields.message: 'Cookies was created successfully',
        }

class RegisterCommand(Command):

    def execute(self, storage: CookieStorage, client: Client, json_data: Dict) -> Dict:
        if not storage.get_cookies(client.hash):
            SERVER_LOGGER.info(f'Client {client.full_address} sent {Fields.hash} {client.hash}, which not in storage')
            client.unregister()
            return {
                Fields.result: False,
                Fields.message: f'Hash {client.hash} not found in storage',
            }
        try:
            client.register()
        except NoAccountException:
            SERVER_LOGGER.info(
                f'Client {client.full_address} unsuccessfully executed {Commands.register} command. {Fields.hash} not found.',
            )
            return {
                Fields.result: False,
                Fields.message: f'You must send {Fields.hash}',
            }
        SERVER_LOGGER.info(f'Client {client.full_address} successfully executed {Commands.register} command')
        return {
            Fields.result: True,
            Fields.message: f'You was successfully registered for cookie dispatching',
            Fields.payload: storage.get_cookies(client.hash),
        }

class DeleteCommand(Command):

    def execute(self, storage: CookieStorage, client: Client, json_data: Dict) -> Dict:
        if not client.hash:
            SERVER_LOGGER.info(f'Client {client.full_address} does not sent hash')
            result = {
                Fields.result: False,
                Fields.message: f'You must send {Fields.hash}',
            }
            return result
        try:
            storage.remove_file(client.hash)
        except AccountNotInStorageError:
            SERVER_LOGGER.info(f'Client {client.full_address} account {client.hash} not found in storage')
            return {
                Fields.result: False,
                Fields.message: f'Storage account {client.hash} was not found, so no account was removed',
            }
        client.unregister()
        SERVER_LOGGER.info(f'Client {client.full_address} successfully executed {Commands.delete} command. Cookies {client.hash} removed')
        result = {
            Fields.result: True,
            Fields.message: f'Account {client.hash} was removed successfully',
        }
        return result

class SetCookiesCommand(Command):

    def execute(self, storage: CookieStorage, client: Client, json_data: Dict) -> Dict:
        if not client.hash:
            SERVER_LOGGER.info(f'Client {client.full_address} does not sent hash')
            return {
                Fields.result: False,
                Fields.message: f'You should send {Fields.hash}',
            }
        if not client.is_registered():
            SERVER_LOGGER.info(f'Client {client.full_address} was not registered, so cookies cannot be set')
            return {
                Fields.result: False,
                Fields.message: f'You should send {Commands.register} command first',
            }
        cookies = json_data.get(Fields.payload)
        if not cookies:
            SERVER_LOGGER.info(f'Client {client.full_address} does not sent cookies')
            return {
                Fields.result: False,
                Fields.message: f'You should send {Fields.payload} data',
            }
        try:
            storage.set_cookies(client.hash, cookies)
        except SetCookiesTimeoutError:
            SERVER_LOGGER.info(f'Client {client.full_address} tried to set new cookies, but they was already set successfully by other client')
            return {
                Fields.result: False,
                Fields.message: 'Cookies already have set successfully',
            }
        except AccountNotInStorageError:
            SERVER_LOGGER.info(f'Client {client.full_address} tried to set non-existent account {client.hash}, so nothing was set')
            return {
                Fields.result: False,
                Fields.message: f'Account {client.hash} does not exist, nothing was set',
            }
        except SameCookiesError:
            SERVER_LOGGER.info(f'Client {client.full_address} tried to set same cookie {client.hash}')
            return {
                Fields.result: False,
                Fields.message: 'This cookies was already set successfully',
            }
        request_id = json_data.get('request_id')
        self._send_cookies_to_clients(client, cookies, request_id)
        SERVER_LOGGER.info(f'Client {client.full_address} successfully set {client.hash} cookies')
        return {
            Fields.result: True,
            Fields.message: 'Cookies was set successfully',
        }

    @staticmethod
    def _send_cookies_to_clients(client: Client, new_cookies: List[Dict], request_id: str) -> None:
        # проверку словаря делали в execute
        for other_client in client.registered_clients[client.hash]:
            if client is other_client:
                continue
            output = {
                Fields.request_id: request_id,
                Fields.command: Commands.set,
                Fields.payload: new_cookies,
            }
            output_json = json.dumps(output).encode(ENCODING)
            #todo а если клиент в это время отключится?
            other_client.socket.sendall(len(output_json).to_bytes(4, 'big') + output_json)

class GetCookiesCommand(Command):

    def execute(self, storage: CookieStorage, client: Client, json_data: Dict) -> Dict:
        if not client.hash:
            SERVER_LOGGER.info(f'Client {client.full_address} does not sent {Fields.hash}')
            return {
                Fields.result: False,
                Fields.message: f'You should send {Fields.hash}',
            }
        try:
            cookies = storage.get_cookies(client.hash)
        except AccountNotInStorageError:
            SERVER_LOGGER.info(
                f'Client {client.full_address} tried to get cookies {client.hash}, but they are not in storage',
            )
            return {
                Fields.result: False,
                Fields.message: f'You tried to get cookies {client.hash}, but they are not in storage',
            }
        SERVER_LOGGER.info(f'Client {client.full_address} successfully executed {Commands.get} command')
        return {
            Fields.result: True,
            Fields.payload: cookies,
        }
