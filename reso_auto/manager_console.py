"""Console for manage pinned message."""

import json
from random import getrandbits

from telebot.apihelper import ApiTelegramException

from reso_auto.manager import MessageManager


class Console:
    """Pinned message console class."""

    manager = MessageManager()
    BITS = 128
    accounts = None

    @classmethod
    def initial_error_handler(cls, error_code: int) -> None:
        if error_code == 400:
            exit('Чат {chat} не найден необходимо написать боту /start'.format(chat=cls.manager.chat))
        elif error_code == 401:
            exit('Токен {token} не валиден, бот не существует.'.format(token=cls.manager.bot.token))
        elif error_code == 0:
            print(
                'Бот существует, но отсутствует закрепленное сообщение. Создать новое сообщение с исходнымы куками?',
                end='\n',
            )
            command = input('1 - Да\n2 - Выход\n')
            if command == '1':
                cls.manager.reinit()
                cls.accounts = list(json.loads(cls.manager.bot.get_chat(chat_id=cls.manager.chat).pinned_message.text).keys())
            else:
                exit()

    @classmethod
    def _available_accounts_print(cls) -> None:
        """Available message print function."""
        print('Сейчас на сервере доступны следующие аккаунты:\n')
        for num, hsh in enumerate(cls.accounts, start=1):
            print(f'{num}) {hsh}')

    @classmethod
    def main(cls) -> None:
        """Main console function."""
        try:
            cls.accounts = list(json.loads(cls.manager.bot.get_chat(chat_id=cls.manager.chat).pinned_message.text).keys())
        except ApiTelegramException as error:
            cls.initial_error_handler(error.error_code)
        except AttributeError:
            cls.initial_error_handler(0)
        command = ''
        menu = '\nКоманды:\n1 - Добавить новый аккаунт\n2 - Удалить существующий аккаунт\n3 - Сбросить сообщение к изначальным настройкам\n4 - Выход'

        while command != '4':
            cls._available_accounts_print()
            print(menu)
            command = input('Ввод: ')
            if command == '1':
                name = input('Имя, которое будет добавлено к хэшу (можно оставить пустым): ')
                hsh = '{hash}_{name}'.format(hash=str(getrandbits(cls.BITS)), name=name)
                cls.manager.add_account(hsh)
                print(f'Новый хэш: {hsh}', end='\n\n')
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


if __name__ == '__main__':
    Console.main()
