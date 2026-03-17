import json
import os
import time
from functools import cached_property
from typing import Dict, List, Optional, Set

from cookieserver.src.client import Client
from cookieserver.src.errors import StorageError
from cookieserver.src.settings import ACCOUNTS_PATH, COOKIE_TIMEOUT, SRC_PATH
import asyncio
import logging

logger = logging.getLogger(__name__)


class Account:

    def __init__(self, name, payload):
        self.name = name
        self.payload = payload
        self.updated_at = time.time()
        filename = f'{self.name}.json'
        self.full_path = os.path.join(ACCOUNTS_PATH, filename)
        self.lock = asyncio.Lock()

    def set_payload(self, payload):
        if payload == self.payload:
            raise StorageError('Payload is same, set is failed')
        if time.time() - self.updated_at < COOKIE_TIMEOUT:
            raise StorageError('This account has already set by other client recently. Try again later')
        self.updated_at = time.time()
        self.payload = payload
        self.write_file()

    def write_file(self):
        with open(self.full_path, 'w') as f:
            f.write(json.dumps(self.payload))

    def remove_file(self):
        if os.path.exists(self.full_path):
            os.remove(self.full_path)
        else:
            raise StorageError(f'File with path {self.full_path} does not exist')

class AccountStorage:

    def __init__(self, clients_by_accounts: Dict[str, Set[Client]]):
        self._accounts: Dict[str, Account] = {}
        self.clients_by_account = clients_by_accounts
        self._load_accounts()

    def _load_accounts(self) -> None:
        for filename in os.listdir(ACCOUNTS_PATH):
            if not filename.endswith(".json"):
                continue

            name = filename.removesuffix(".json")
            path = os.path.join(ACCOUNTS_PATH, filename)

            with open(path) as f:
                payload = json.load(f)

            account = Account(name, payload)
            self._accounts[name] = account

    @cached_property
    def _cookie_sample(self) -> List[Dict]:
        path = os.path.join(SRC_PATH, 'cookie_sample.json')
        with open(path) as f:
            return json.loads(f.read())

    def get_all_accounts(self) -> List[str]:
        return list(self._accounts.keys())

    def get_account(self, account_name: str) -> Optional[Account]:
        """non strict"""
        return self._accounts.get(account_name)

    def require_account(self, account_name: str) -> Account:
        if account := self.get_account(account_name):
            return account
        raise StorageError(f"Account {account_name} does not exist")

    def add_account(self, account_name: str) -> None:
        if self.get_account(account_name):
            raise StorageError(f"Cannot add an existing account {account_name} so it cannot be added")
        account = Account(account_name, payload=self._cookie_sample)
        account.write_file()
        self._accounts[account_name] = account

    def remove_account(self, account_name: str) -> None:
        account = self.get_account(account_name)
        if not account:
            raise StorageError(f"Account {account_name} does not exist so it cannot be removed")
        account.remove_file()
        self._accounts.pop(account_name)

        # если у аккаунта были клиенты, нужно обработать отключение
        # clients = self._account_clients.pop(account_name)
        # for client in clients:
        #     client.writer.close()

    def set_cookies(self, account_name: str, payload: List[Dict]) -> None:
        account = self.require_account(account_name)
        account.set_payload(payload)
