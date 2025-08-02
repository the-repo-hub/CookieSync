"""Pinned message manager module."""

import json
from functools import cached_property
from typing import Dict, List

from telebot import TeleBot
from telebot.apihelper import ApiTelegramException

from src.exceptions import InvalidBotToken, InvalidHash, MessageTooLong
from src.handlers import retry
from src.settings import BOT_TOKEN, CHAT_ID, TELEGRAM_MSG_LIMIT


class MessageManager(object):
    """Account manager class for manage pinned message data."""

    @cached_property
    def message_sample(self) -> Dict:
        """Read json file with message sample.

            Returns:
                JSON message sample.
            """
        # ничего страшного, что это хранится в гит - эти значения генерируются каждый раз заново
        return json.loads('{"test":[{"name":"ASP.NET_SessionId","value":"yrtu1tgknmxnjpeswaygtxqw","path":"/","secure":false,"httpOnly":true,"sameSite":"None","domain":".reso.ru"},{"name":"ResoOffice60","value":"3BDDB47353A1DBFBC4AE88C9659B35F136FEAB9E3F00A7E9F0FB21ADAC89E66B05F3D8E06052F6AF30C5B7628B4610979B604C5DB4046828B1B8658C7657F8AE45D53DE18201013C1492F10EE56F1469575D2D89","path":"/","secure":false,"httpOnly":true,"sameSite":"None","domain":".reso.ru"}]}')

    def __init__(self) -> None:
        """Account manager initial method."""
        self.bot = TeleBot(BOT_TOKEN)
        self.chat = CHAT_ID

    @retry
    def reinit(self) -> None:
        """Initialize or reinitialize pinned message."""
        pinned = self.bot.get_chat(self.chat).pinned_message
        if pinned:
            if pinned.text != json.dumps(self.message_sample):
                self.bot.edit_message_text(
                    chat_id=self.chat,
                    message_id=pinned.message_id,
                    text=json.dumps(self.message_sample),
                )
        else:
            msg = self.bot.send_message(chat_id=self.chat, text=json.dumps(self.message_sample))
            self.bot.pin_chat_message(chat_id=self.chat, message_id=msg.message_id)

    @retry
    def get_telegram_cookies(self, hsh: str) -> List:
        """Get cookies by hash from pinned message.

        Args:
            hsh: user identification hash.

        Returns:
            Telegram cookies dictionary or None, if hash does not exist.
        """
        try:
            pinned = self.bot.get_chat(self.chat).pinned_message
        except ApiTelegramException:
            raise InvalidBotToken(InvalidBotToken.msg)
        if not pinned:
            self.reinit()
        try:
            return json.loads(pinned.text)[hsh]
        except KeyError:
            raise InvalidHash(InvalidHash.msg.format(hash=hsh))

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
        if len(str(as_json)) >= TELEGRAM_MSG_LIMIT:
            raise MessageTooLong(MessageTooLong.msg)
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
