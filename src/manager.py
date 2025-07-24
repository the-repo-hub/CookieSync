"""Pinned message manager module."""

import json
from typing import Dict, List, Union

from telebot import TeleBot

from src.choiches import ErrorMessages
from src.handlers import retry
from src.settings import BOT_TOKEN, CHAT_ID, MESSAGE_SAMPLE_PATH


def get_message_sample() -> Dict:
    """Read json file with message sample.

    Returns:
        JSON message sample.
    """
    with open(MESSAGE_SAMPLE_PATH) as dct:
        return json.loads(dct.read())


class MessageManager(object):
    """Account manager class for manage pinned message data."""

    message_sample = get_message_sample()

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
    def get_telegram_cookies(self, hsh: str) -> Union[str, List]:
        """Get cookies by hash from pinned message.

        Args:
            hsh: user identification hash.

        Returns:
            Telegram cookies dictionary or None, if hash does not exist.
        """
        try:
            pinned = self.bot.get_chat(self.chat).pinned_message
        except Exception:
            return ErrorMessages.token_error.value
        if not pinned:
            self.reinit()
        try:
            return json.loads(pinned.text)[hsh]
        except KeyError:
            return ErrorMessages.invalid_hash.value

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
