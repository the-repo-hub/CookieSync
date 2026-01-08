import json
import os
import time
from functools import cached_property
from typing import Dict, List

from cookieserver.src.settings import ACCOUNTS_PATH, SRC_PATH, SERVER_LOGGER, COOKIE_TIMEOUT

class AccountNotInStorageError(Exception):
    pass

class SetCookiesTimeoutError(Exception):
    pass

class SameCookiesError(Exception):
    pass

class AccountAlreadyExists(Exception):
    pass

class CookieStorage:

    def __init__(self):
        self._accounts: Dict[str, List[Dict]] = {}
        self._cookie_timer: Dict[str, float] = {}
        self._init_accounts()

    def _init_accounts(self) -> None:
        os.makedirs(ACCOUNTS_PATH, exist_ok=True)
        for filename in os.listdir(ACCOUNTS_PATH):
            hsh = filename.split('.')[0]
            file = open(os.path.join(ACCOUNTS_PATH, filename))
            try:
                self._accounts[hsh] = json.loads(file.read())
            except json.decoder.JSONDecodeError:
                file.close()
                SERVER_LOGGER.warning(f'Error in decoding {filename}, passing this file.')
                continue
            self._cookie_timer[hsh] = 0
            file.close()

    @cached_property
    def _cookie_sample(self) -> List[Dict]:
        path = os.path.join(SRC_PATH, 'cookie_sample.json')
        with open(path) as f:
            return json.loads(f.read())

    def _write_to_file(self, hsh: str):
        filename = f'{hsh}.json'
        full_path = os.path.join(ACCOUNTS_PATH, filename)
        os.makedirs(ACCOUNTS_PATH, exist_ok=True)
        with open(full_path, 'w') as f:
            f.write(
                json.dumps(self._accounts[hsh]),
            )

    def get_all_accounts(self) -> List[str]:
        return list(self._accounts.keys())

    def get_cookies(self, hsh: str) -> List[Dict]:
        cookies = self._accounts.get(hsh)
        if not cookies:
            raise AccountNotInStorageError
        return cookies

    def add_file(self, hsh: str) -> None:
        if hsh in self._accounts:
            raise AccountAlreadyExists
        self._accounts[hsh] = self._cookie_sample
        self._write_to_file(hsh)
        self._cookie_timer[hsh] = time.time()

    def remove_file(self, hsh: str) -> None:
        filename = f'{hsh}.json'
        try:
            self._accounts.pop(hsh)
        except KeyError:
            raise AccountNotInStorageError
        try:
            os.remove(os.path.join(ACCOUNTS_PATH, filename))
        except FileNotFoundError:
            SERVER_LOGGER.warning(f'Cookie file {filename} not found, but account {hsh} removed.')

    def set_cookies(self, hsh: str, new_cookies: List[Dict]) -> None:
        if not self._accounts.get(hsh):
            raise AccountNotInStorageError
        if time.time() - self._cookie_timer[hsh] < COOKIE_TIMEOUT:
            raise SetCookiesTimeoutError
        if new_cookies == self._accounts[hsh]:
            raise SameCookiesError
        self._accounts[hsh] = new_cookies
        self._cookie_timer[hsh] = time.time()
        self._write_to_file(hsh)
