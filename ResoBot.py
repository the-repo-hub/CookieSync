import telebot
import random
import hashlib
import ast
from selenium.common.exceptions import WebDriverException
from telebot.apihelper import ApiTelegramException
import time
import ctypes
from sys import exit
from requests.exceptions import ConnectionError


def raise_error(error_txt):
    ctypes.windll.user32.MessageBoxW(0, error_txt, "Error message", 0)
    exit(1)


def retry(fn):

    def inner(*args, **kwargs):
        err_counter = 0
        err_type = ''
        while err_counter <= 40:
            try:
                return fn(*args, **kwargs)

            # проблемы с интернетом
            except ConnectionError:
                err_counter += 1
                err_type = 'ConnectionError'

            # проблемы с интернетом для браузера
            except WebDriverException:
                err_counter += 1
                err_type = 'WebDriverException'

            # проблемы с телеграмом
            except ApiTelegramException:
                err_counter += 1
                err_type = 'ApiTelegramException'

            time.sleep(random.randint(1, 7))
        raise_error(f"Проблемы с интернетом.\nТип ошибки: {err_type}\nФункция: {fn.__name__}")
    return inner


class ResoBot(telebot.TeleBot):
    def __init__(self, token):
        self.token = token
        self.chat = 408972919

        super().__init__(token)


class AccountManager:

    def __init__(self):
        # FIXME token
        self.bot = ResoBot('')
        self.pinned_message_id = None
        self.cookie_sample = [{'name': 'ASP.NET_SessionId', 'value': 'sample', 'path': '/', 'secure': False, 'httpOnly': True, 'sameSite': 'None'},
                              {'name': 'ResoOffice60', 'value': 'sample', 'path': '/', 'secure': False, 'httpOnly': True, 'sameSite': 'None'}]
        self.none_msg = "NONE"
        self.accounts = list(self.dict().keys())

    @staticmethod
    def generate_hash(txt=''):
        code_phrase = ''.join([chr(random.randint(1, 125)) for i in range(random.randint(100, 1000))])
        return hashlib.md5(code_phrase.encode('utf-8')).hexdigest() + '_' + txt

    @retry
    def dict(self):
        try:
            msg = self.bot.get_chat(self.bot.chat).pinned_message
            if not msg:
                raise ApiTelegramException(self.dict, None, {'error_code': 1, 'description': 'msg is None'})
            self.pinned_message_id = msg.message_id
            return self._dct_from_txt(msg.text)
        except KeyError:
            return None

    @staticmethod
    def _dct_from_txt(txt):
        d = {}
        split = txt.split('\n\n')
        for i in range(0, len(split) - 1, 2):
            d[split[i]] = list(map(ast.literal_eval, split[i+1].split('\n')))
        return d

    @retry
    def _edit(self, dct):
        if not dct:
            txt = self.none_msg
        else:
            txt = ''
            for key, value in dct.items():
                txt += key + '\n\n'
                for dct in value:
                    txt += str(dct) + '\n'
                txt += '\n'
            txt = txt[:-2]
        try:
            self.bot.edit_message_text(txt, self.bot.chat, self.pinned_message_id)
        except ApiTelegramException:
            pass

    def add_account(self, hsh, cookie=None):
        if not cookie:
            cookie = self.cookie_sample
        dct = self.dict()
        if self.none_msg in dct.keys():
            dct.clear()
        dct[hsh] = cookie
        if hsh not in self.accounts:
            self.accounts.append(hsh)
        self._edit(dct)

    def remove_account(self, hsh):
        dct = self.dict()
        if self.none_msg in dct.keys():
            dct.clear()
        dct.pop(hsh)
        self.accounts.remove(hsh)
        self._edit(dct)

    def get_account(self, hsh):
        try:
            result = self.dict()[hsh]
            return result
        except KeyError:
            return None

    def __getitem__(self, item):
        return self.get_account(item)

    def __setitem__(self, key, value):

        self.add_account(key, value)

    def __delitem__(self, key):
        self.remove_account(key)

    @retry
    def update(self):
        with open('cookie_for_restore.txt') as file:
            txt = file.read()
            self.bot.edit_message_text(message_id=self.pinned_message_id, chat_id=self.bot.chat, text=txt)


if __name__ == '__main__':
    AccountManager().update()
