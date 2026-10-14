import asyncio
import json
import logging
import math
import os
import re
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Set

from websockets.asyncio.server import ServerConnection

from cookieserver.src.errors import StorageError
from cookieserver.src.settings import (
    ACCOUNTS_PATH,
    COOKIE_UPDATE_INTERVAL,
    ENCODING,
)

logger = logging.getLogger(__name__)

SYNC_COOKIE_ORDER = ('ASP.NET_SessionId', 'ResoOffice60')
SYNC_COOKIE_NAMES = frozenset(SYNC_COOKIE_ORDER)
RESERVED_ACCOUNT_NAMES = {
    'CON', 'PRN', 'AUX', 'NUL',
    *(f'COM{i}' for i in '123456789¹²³'),
    *(f'LPT{i}' for i in '123456789¹²³'),
}


@dataclass(frozen=True)
class CookieUpdateResult:
    accepted: bool
    changed: bool
    retry_after: int


def filter_sync_cookies(payload: object) -> List[Dict]:
    if not isinstance(payload, list):
        return []
    return [
        cookie for cookie in payload
        if isinstance(cookie, dict) and cookie.get('name') in SYNC_COOKIE_NAMES
    ]


def require_complete_cookie_pair(payload: object) -> List[Dict]:
    cookies = filter_sync_cookies(payload)
    names = [cookie.get('name') for cookie in cookies]
    if len(cookies) != len(SYNC_COOKIE_NAMES) or set(names) != SYNC_COOKIE_NAMES:
        required = ', '.join(sorted(SYNC_COOKIE_NAMES))
        raise StorageError(f'Cookie payload must contain exactly one of each: {required}')
    for cookie in cookies:
        if not isinstance(cookie.get('value'), str) or not cookie['value']:
            raise StorageError(f"Cookie {cookie['name']} must have a non-empty string value")
        domain = cookie.get('domain')
        if not isinstance(domain, str) or not domain.strip():
            raise StorageError(f"Cookie {cookie['name']} must have a domain")
        path = cookie.get('path')
        if not isinstance(path, str) or not path.startswith('/'):
            raise StorageError(f"Cookie {cookie['name']} must have a path")
        for field in ('secure', 'httpOnly', 'hostOnly'):
            if field in cookie and not isinstance(cookie[field], bool):
                raise StorageError(f"Cookie {cookie['name']} has invalid {field}")
        if 'sameSite' in cookie and cookie['sameSite'] not in {
            'no_restriction', 'lax', 'strict', 'unspecified',
        }:
            raise StorageError(f"Cookie {cookie['name']} has invalid sameSite")
        if 'expirationDate' in cookie:
            expiration = cookie['expirationDate']
            if (
                not isinstance(expiration, (int, float))
                or isinstance(expiration, bool)
                or not math.isfinite(expiration)
                or expiration <= time.time()
            ):
                raise StorageError(
                    f"Cookie {cookie['name']} has invalid expirationDate"
                )
    cookies_by_name = {cookie['name']: cookie for cookie in cookies}
    return [cookies_by_name[name] for name in SYNC_COOKIE_ORDER]


class Account:

    def __init__(self, name, payload, updated_at=0.0, revision=0):
        self.name = name
        self.payload = payload
        self.updated_at = updated_at
        self.revision = revision
        elapsed = max(0.0, time.time() - self.updated_at)
        remaining = max(0.0, COOKIE_UPDATE_INTERVAL - elapsed)
        self._locked_until = time.monotonic() + remaining
        filename = f'{self.name}.json'
        self.full_path = os.path.join(ACCOUNTS_PATH, filename)
        self.lock = asyncio.Lock()

    def retry_after(self) -> int:
        remaining = self._locked_until - time.monotonic()
        return max(0, math.ceil(remaining))

    def set_payload(self, payload, expected_revision: Optional[int] = None) -> CookieUpdateResult:
        if expected_revision is not None:
            if type(expected_revision) is not int or expected_revision < 0:
                raise StorageError('expected_revision must be a non-negative integer')
            if expected_revision != self.revision:
                return CookieUpdateResult(
                    accepted=False, changed=False, retry_after=self.retry_after(),
                )
        if payload == self.payload:
            return CookieUpdateResult(
                accepted=True,
                changed=False,
                retry_after=self.retry_after(),
            )
        retry_after = self.retry_after()
        if retry_after and expected_revision is None:
            return CookieUpdateResult(
                accepted=False,
                changed=False,
                retry_after=retry_after,
            )
        now = time.time()
        previous_payload = self.payload
        previous_updated_at = self.updated_at
        previous_revision = self.revision
        previous_locked_until = self._locked_until
        self.updated_at = now
        self.payload = payload
        self.revision += 1
        self._locked_until = time.monotonic() + COOKIE_UPDATE_INTERVAL
        try:
            self.write_file()
        except OSError:
            self.payload = previous_payload
            self.updated_at = previous_updated_at
            self.revision = previous_revision
            self._locked_until = previous_locked_until
            raise
        return CookieUpdateResult(
            accepted=True,
            changed=True,
            retry_after=COOKIE_UPDATE_INTERVAL,
        )

    def write_file(self):
        document = {
            'payload': self.payload,
            'updated_at': self.updated_at,
            'revision': self.revision,
        }
        temp_path = f'{self.full_path}.tmp'
        with open(temp_path, 'w', encoding=ENCODING) as file_obj:
            json.dump(document, file_obj)
        os.replace(temp_path, self.full_path)


class AccountStorage:

    def __init__(self):
        self._accounts: Dict[str, Account] = {}
        self._creation_lock = asyncio.Lock()
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

    def require_registered_client(self, websocket: ServerConnection, account_name: str) -> None:
        if self._ws_accounts.get(websocket) != account_name:
            raise StorageError('Register in this account before refreshing cookies')

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
                with open(path, encoding=ENCODING) as file_obj:
                    document = json.load(file_obj)
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(f"Skipping unreadable account file {path}: {e}")
                continue

            if isinstance(document, dict):
                payload = document.get('payload', [])
                updated_at = document.get('updated_at', 0.0)
                revision = document.get('revision', 0)
            else:
                payload = document
                updated_at = 0.0
                revision = 0

            try:
                filtered_payload = (
                    require_complete_cookie_pair(payload) if payload else []
                )
            except StorageError:
                filtered_payload = []
            if (
                not isinstance(updated_at, (int, float))
                or isinstance(updated_at, bool)
                or not math.isfinite(updated_at)
                or updated_at < 0
            ):
                updated_at = 0.0
            if not isinstance(revision, int) or isinstance(revision, bool) or revision < 0:
                revision = 0
            if not filtered_payload:
                updated_at = 0.0
                revision = 0
            elif updated_at > time.time():
                updated_at = time.time()

            account = Account(name, filtered_payload, float(updated_at), revision)
            self._accounts[name] = account
            expected_document = {
                'payload': filtered_payload,
                'updated_at': float(updated_at),
                'revision': revision,
            }
            if document != expected_document:
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

    async def get_or_create_account(self, account_name: str) -> Account:
        if not isinstance(account_name, str) or not account_name.strip():
            raise StorageError('Account name must be a non-empty string')
        if account := self.get_account(account_name):
            return account
        # Existing accounts retain their names; new names must be safe filenames
        # on both Linux and Windows (including reserved Windows device names).
        if (
            not re.fullmatch(r'[\w-]{1,64}', account_name)
            or len(account_name.encode('utf-8')) > 200
            or account_name.upper() in RESERVED_ACCOUNT_NAMES
        ):
            raise StorageError(
                'Invalid account name: use 1-64 letters, digits, underscores or hyphens; '
                'reserved device names are not allowed'
            )
        async with self._creation_lock:
            if account := self.get_account(account_name):
                return account
            account = Account(account_name, [])
            async with account.lock:
                write_task = asyncio.create_task(
                    asyncio.to_thread(self._persist_new_account, account)
                )
                try:
                    await asyncio.shield(write_task)
                except asyncio.CancelledError:
                    # A filesystem write cannot be cancelled. Finish it before
                    # releasing the creation lock so another client can reuse it.
                    await write_task
                    self._accounts[account_name] = account
                    raise
                self._accounts[account_name] = account
            logger.info('Created account %s on registration', account_name)
            return account

    @staticmethod
    def _persist_new_account(account: Account) -> None:
        os.makedirs(ACCOUNTS_PATH, exist_ok=True)
        if os.path.lexists(account.full_path):
            # Do not overwrite an unreadable file skipped at startup, or a
            # differently cased name on a case-insensitive filesystem.
            raise StorageError('Account file already exists but could not be loaded under this name')
        account.write_file()

    def set_cookies(
        self, account_name: str, payload: List[Dict],
        *, expected_revision: Optional[int] = None,
    ) -> CookieUpdateResult:
        account = self.require_account(account_name)
        return account.set_payload(require_complete_cookie_pair(payload), expected_revision)
