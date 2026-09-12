import asyncio
import json
import logging
import os
import time
from typing import Dict, List, Optional, Set

from websockets.asyncio.server import ServerConnection

from cookieserver.src.errors import StorageError
from cookieserver.src.settings import ACCOUNTS_PATH, COOKIE_TIMEOUT
from cookieserver.src.request import Request

logger = logging.getLogger(__name__)


class Account:

    def __init__(self, name, payload):
        self.name = name
        self.payload = payload
        self.updated_at = 0.0
        filename = f'{self.name}.json'
        self.full_path = os.path.join(ACCOUNTS_PATH, filename)
        self.lock = asyncio.Lock()

    def set_payload(self, payload):
        if payload == self.payload:
            raise StorageError('Payload is same, set is failed')
        now = time.time()
        if now - self.updated_at < COOKIE_TIMEOUT:
            remaining = int(COOKIE_TIMEOUT - (now - self.updated_at))
            raise StorageError(
                f'Rate limit: try again in {remaining}s'
            )
        self.updated_at = now
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

    def __init__(self):
        self._accounts: Dict[str, Account] = {}
        self.websockets_by_account: Dict[str, Set[ServerConnection]] = {}
        self._load_accounts()

    def _load_accounts(self) -> None:
        for filename in os.listdir(ACCOUNTS_PATH):
            if not filename.endswith(".json"):
                continue

            name = filename.removesuffix(".json")
            path = os.path.join(ACCOUNTS_PATH, filename)

            try:
                with open(path) as f:
                    payload = json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(f"Skipping unreadable account file {path}: {e}")
                continue

            account = Account(name, payload)
            self._accounts[name] = account

    def get_all_accounts(self) -> List[str]:
        return list(self._accounts.keys())

    def get_account(self, account_name: str) -> Optional[Account]:
        """non strict"""
        return self._accounts.get(account_name)

    def require_account(self, account_name: str) -> Account:
        if account := self.get_account(account_name):
            return account
        raise StorageError(f"Account {account_name} does not exist")

    def add_account(self, account_name: str, payload: Optional[List[Dict]] = None) -> None:
        if self.get_account(account_name):
            raise StorageError(f"Cannot add an existing account {account_name} so it cannot be added")
        account = Account(account_name, payload=payload or [])
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

    def set_cookies(self, account_name: str, request: Request) -> None:
        account = self.require_account(account_name)
        account.set_payload(request.payload)
