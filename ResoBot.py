import json
from typing import Dict, Optional

from telebot import TeleBot

from support import retry


class AccountManager:

    def __init__(self) -> None:
        # FIXME token
        self.bot = TeleBot('6373412192:AAGbi-48XKPjBUuQOHWtGsMA1aesYxzzYK4')
        self.chat = 408972919
        self.message_sample = {
            'test': {
                'ResoOffice60':
                    {'name': 'ASP.NET_SessionId', 'value': 'sample', 'path': '/', 'secure': False, 'httpOnly': True,
                     'sameSite': 'None', 'domain': 'office.reso.ru'},
                'ASP.NET_SessionId':
                    {'name': 'ResoOffice60', 'value': 'sample', 'path': '/', 'secure': False, 'httpOnly': True,
                     'sameSite': 'None', 'domain': 'office.reso.ru'},
            }
        }

    def reinit(self) -> None:
        pinned = self.bot.get_chat(self.chat).pinned_message
        if pinned:
            self.bot.edit_message_text(chat_id=self.chat, message_id=pinned.message_id, text=json.dumps(self.message_sample))
        else:
            msg = self.bot.send_message(chat_id=self.chat, text=str(self.message_sample))
            self.bot.pin_chat_message(chat_id=self.chat, message_id=msg.message_id)

    @retry
    def get_telegram_cookies(self, hsh: str) -> Optional[Dict]:
        pinned = self.bot.get_chat(self.chat).pinned_message
        if not pinned:
            self.reinit()
        try:
            return json.loads(pinned.text)[hsh]
        except KeyError:
            return None

    @retry
    def set_telegram_cookies(self, cookies: Dict, hsh: str) -> None:
        pinned = self.bot.get_chat(self.chat).pinned_message
        as_json = json.loads(pinned.text)
        as_json[hsh] = cookies
        self.bot.edit_message_text(chat_id=self.chat, message_id=pinned.message_id, text=json.dumps(as_json))
