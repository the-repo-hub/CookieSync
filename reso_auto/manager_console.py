"""Console for manage pinned message."""

import json
from random import getrandbits
from typing import List

from manager import AccountManager

manager = AccountManager()
BITS = 128


def available_accounts_print(accounts: List) -> None:
    """Available message print function.

    Args:
        accounts: list with accounts (hashes).
    """
    print('Сейчас на сервере доступны следующие аккаунты:\n')
    for num, hsh in enumerate(accounts, start=1):
        print(f'{num}) {hsh}')


def main() -> None:
    """Main console function."""
    command = ''
    menu = '\nКоманды:\n1 - Добавить новый аккаунт\n2 - Удалить существующий аккаунт\n3 - Сбросить сообщение к изначальным настройкам\n4 - Выход'
    accounts = list(json.loads(manager.bot.get_chat(chat_id=manager.chat).pinned_message.text).keys())
    while command != '4':
        available_accounts_print(accounts)
        print(menu)
        command = input('Ввод: ')
        if command == '1':
            name = input('Имя, которое будет добавлено к хэшу (можно оставить пустым): ')
            hsh = str(getrandbits(BITS)) + name
            manager.add_account(hsh)
            print(f'Новый хэш: {hsh}', end='\n\n')
            accounts.append(hsh)

        elif command == '2':
            num = int(input('Номер хэша, который необходимо удалить: ')) - 1
            hsh = accounts[num]
            if hsh in accounts:
                manager.remove_account(hsh)
                accounts.pop(num)
                print(f'Хэш {command} удалён.')
            else:
                print('Хэша нет в списке!')

        elif command == '3':
            manager.reinit()
            accounts = list(json.loads(manager.bot.get_chat(chat_id=manager.chat).pinned_message.text).keys())
            print('Сообщение сброшено к изначальным настройкам.')


if __name__ == '__main__':
    main()
