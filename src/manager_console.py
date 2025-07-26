"""Console for manage pinned message."""

import json
from http import HTTPStatus
from random import getrandbits
from typing import List

from telebot.apihelper import ApiTelegramException

from src.manager import MessageManager
from src.exceptions import MessageTooLong

class Console(object):
    """Pinned message console class."""

    manager = MessageManager()
    bits = 128
    accounts: List

    @classmethod
    def command_handler(cls, command: str) -> None:
        """Command cycle handler.

        Args:
            command: stringified num of option
        """
        if command == '1':
            name = input('Имя, которое будет добавлено к хэшу (можно оставить пустым): ')
            hsh = '{hash}_{name}'.format(hash=str(getrandbits(cls.bits)), name=name)
            try:
                cls.manager.add_account(hsh)
            except MessageTooLong:
                print(MessageTooLong.msg)
            else:
                print('Новый хэш: {hsh}'.format(hsh=hsh), end='\n\n')
                cls.accounts.append(hsh)

        elif command == '2':
            num = int(input('Номер хэша, который необходимо удалить: ')) - 1
            hsh = cls.accounts[num]
            if hsh in cls.accounts:
                cls.manager.remove_account(hsh)
                cls.accounts.pop(num)
                print('Хэш {hsh} удалён.'.format(hsh=hsh))
            else:
                print('Хэша нет в списке!')

        elif command == '3':
            cls.manager.reinit()
            cls.accounts = list(
                json.loads(cls.manager.bot.get_chat(chat_id=cls.manager.chat).pinned_message.text).keys(),
            )
            print('Сообщение сброшено к изначальным настройкам.')

    @classmethod
    def main(cls) -> None:
        """Console execution."""
        try:
            cls.accounts = list(
                json.loads(cls.manager.bot.get_chat(chat_id=cls.manager.chat).pinned_message.text).keys(),
            )
        except ApiTelegramException as error:
            cls._initial_error_handler(error.error_code)
        except AttributeError:
            cls._initial_error_handler(0)
        except Exception:
            cls._initial_error_handler(HTTPStatus.UNAUTHORIZED)
        command = ''
        menu = '\nКоманды:\n1 - Добавить новый аккаунт\n2 - Удалить существующий аккаунт\n3 - Сбросить сообщение к изначальным настройкам\n4 - Выход'

        while command != '4':
            cls._available_accounts_print()
            print(menu)
            command = input('Ввод: ')
            cls.command_handler(command)

    @classmethod
    def _available_accounts_print(cls) -> None:
        """Available message print function."""
        print('Сейчас на сервере доступны следующие аккаунты:\n')
        for num, hsh in enumerate(cls.accounts, start=1):
            print('{num}) {hsh}'.format(num=num, hsh=hsh))

    @classmethod
    def _initial_error_handler(cls, error_code: int) -> None:
        """Handle initial errors, like invalid token or chat.

        Args:
            error_code: standard http error code.
        """
        if error_code == HTTPStatus.BAD_REQUEST:
            exit('Чат {chat} не найден необходимо написать боту /start'.format(chat=cls.manager.chat))
        elif error_code == HTTPStatus.UNAUTHORIZED:
            exit('Токен {token} не валиден, бот не существует.'.format(token=cls.manager.bot.token))
        elif error_code == 0:
            print(
                'Бот существует, но отсутствует закрепленное сообщение. Создать новое сообщение с исходнымы куками?',
                end='\n',
            )
            command = input('1 - Да\n2 - Выход\n')
            if command == '1':
                cls.manager.reinit()
                cls.accounts = list(
                    json.loads(cls.manager.bot.get_chat(chat_id=cls.manager.chat).pinned_message.text).keys(),
                )
            else:
                exit(0)


if __name__ == '__main__':
    try:
        Console.main()
    except KeyboardInterrupt:
        exit(0)
