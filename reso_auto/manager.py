"""Pinned message manager module."""

import json
from typing import Dict, Optional, List

from telebot import TeleBot

from reso_auto.handlers import retry


class MessageManager(object):
    """Account manager class for manage pinned message data."""

    message_sample = {
        'test':
            [
                {
                    'name': 'ASP.NET_SessionId',
                    'value': 'yipellveieo2a3zqeqzp0i4x',
                    'path': '/',
                    'secure': False,
                    'httpOnly': True,
                    'sameSite': 'None',
                    'domain': 'office.reso.ru',
                },
                {
                    'name': 'ResoOffice60',
                    'value': 'D8F3B2901DF22BB1B2BBFE1C60038B9428298E0B4F2F89677388C3A0CAC19ECF0C4234101414E289B0247EB1B39430F0C6A5DBD483BFF0A7DF198B42AEB3039BABAFB8403F1011D02CA712DE98C9D9BA3FF65A41071F98078D7CFA4E98210400704D891FC4969BB3CCB5BD4A3FA46AAC',
                    'path': '/',
                    'secure': False,
                    'httpOnly': True,
                    'sameSite': 'None',
                    'domain': 'office.reso.ru',
                },
            ],
    }

    def __init__(self) -> None:
        """Account manager initial method."""
        # FIXME token
        self.bot = TeleBot('6486270881:AAFMgY_fX8_hlb9pr-9XSiLCv7TPLRS6IT0')
        self.chat = 408972919

    @retry
    def reinit(self) -> None:
        """Initialize or reinitialize pinned message."""
        pinned = self.bot.get_chat(self.chat).pinned_message
        if pinned:
            self.bot.edit_message_text(
                chat_id=self.chat,
                message_id=pinned.message_id,
                text=json.dumps(self.message_sample),
            )
        else:
            msg = self.bot.send_message(chat_id=self.chat, text=json.dumps(self.message_sample))
            self.bot.pin_chat_message(chat_id=self.chat, message_id=msg.message_id)

    @retry
    def get_telegram_cookies(self, hsh: str) -> Optional[List]:
        """Get cookies by hash from pinned message.

        Args:
            hsh: user identification hash.

        Returns:
            Telegram cookies dictionary or None, if hash does not exist.
        """
        pinned = self.bot.get_chat(self.chat).pinned_message
        if not pinned:
            self.reinit()
        try:
            return json.loads(pinned.text)[hsh]
        except KeyError:
            return None

    @retry
    def set_telegram_cookies(self, cookies: List, hsh: str) -> None:
        """Set new cookies to pinned message by hash.

        Args:
            cookies: cookies dictionary that will be set.
            hsh: user identification hash.
        """
        pinned = self.bot.get_chat(self.chat).pinned_message
        as_json: Dict[str, List] = json.loads(pinned.text)
        as_json[hsh] = cookies
        self.bot.edit_message_text(chat_id=self.chat, message_id=pinned.message_id, text=json.dumps(as_json))

    def add_account(self, hsh: str) -> None:
        """Add new account to pinned message.

        Args:
            hsh: user identification hash.
        """
        pinned = self.bot.get_chat(self.chat).pinned_message
        as_json = json.loads(pinned.text)
        as_json[hsh] = self.message_sample['test']
        self.bot.edit_message_text(chat_id=self.chat, message_id=pinned.message_id, text=json.dumps(as_json))

    def remove_account(self, hsh: str) -> None:
        """Remove account from pinned message.

        Args:
            hsh: user identification hash.
        """
        pinned = self.bot.get_chat(self.chat).pinned_message
        as_json = json.loads(pinned.text)
        as_json.pop(hsh)
        self.bot.edit_message_text(chat_id=self.chat, message_id=pinned.message_id, text=json.dumps(as_json))
