import asyncio
import json
import logging
import os
import time
from typing import Dict, List, Optional, Set

from websockets.asyncio.server import ServerConnection

from cookieserver.src.errors import StorageError
from cookieserver.src.settings import ACCOUNTS_PATH, COOKIE_TIMEOUT

logger = logging.getLogger(__name__)

SYNC_COOKIE_NAMES = frozenset({'ResoOffice60', 'ASP.NET_SessionId'})


def filter_sync_cookies(payload: object) -> List[Dict]:
    if not isinstance(payload, list):
        return []
    return [
        cookie for cookie in payload
        if isinstance(cookie, dict) and cookie.get('name') in SYNC_COOKIE_NAMES
    ]


class Account:

    def __init__(self, name, payload):
        self.name = name
        self.payload = payload
        self.updated_at = 0.0
        filename = f'{self.name}.json'
        self.full_path = os.path.join(ACCOUNTS_PATH, filename)
        self.lock = asyncio.Lock()

    def set_payload(self, payload) -> bool:
        if payload == self.payload:
            return False
        now = time.time()
        if now - self.updated_at < COOKIE_TIMEOUT:
            remaining = int(COOKIE_TIMEOUT - (now - self.updated_at))
            raise StorageError(
                f'Rate limit: try again in {remaining}s'
            )
        self.updated_at = now
        self.payload = payload
        self.write_file()
        return True

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
        self._ws_accounts: Dict[ServerConnection, str] = {}
        self._load_accounts()

    def add_client(self, websocket: ServerConnection, account_name: str) -> None:
        previous = self._ws_accounts.get(websocket)
        if previous is not None and previous != account_name:
            previous_set = self.websockets_by_account.get(previous)
            if previous_set:
                previous_set.discard(websocket)
        self._ws_accounts[websocket] = account_name
        self.websockets_by_account.setdefault(account_name, set()).add(websocket)

    def remove_client(self, websocket: ServerConnection) -> None:
        account_name = self._ws_accounts.pop(websocket, None)
        if account_name is None:
            return
        ws_set = self.websockets_by_account.get(account_name)
        if ws_set:
            ws_set.discard(websocket)

    def _load_accounts(self) -> None:
        if not os.path.isdir(ACCOUNTS_PATH):
            logger.warning(
                f"Accounts directory {ACCOUNTS_PATH} does not exist, starting empty"
            )
            return
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

            filtered_payload = filter_sync_cookies(payload)
            account = Account(name, filtered_payload)
            self._accounts[name] = account
            if filtered_payload != payload:
                try:
                    account.write_file()
                except OSError as e:
                    logger.warning(f"Could not clean account file {path}: {e}")

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
        account = Account(account_name, payload=filter_sync_cookies(payload or []))
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

    def set_cookies(self, account_name: str, payload: List[Dict]) -> bool:
        account = self.require_account(account_name)
        return account.set_payload(filter_sync_cookies(payload))
