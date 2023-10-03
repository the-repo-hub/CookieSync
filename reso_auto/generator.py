from ResoBot import AccountManager
import json
from random import randint
import hashlib
from typing import List

manager = AccountManager()


def available_msg(accounts: List) -> None:
    print('Сейчас на сервере доступны следующие аккаунты:\n')
    for num, hsh in enumerate(accounts, start=1):
        print(f'{num}) {hsh}')


def new_hash_print(hsh: str) -> None:
    print(f'Новый хэш: {hsh}', end='\n\n')


def generate_hash(name: str = ''):
    code_phrase = ''.join([chr(randint(1, 125)) for i in range(20)])
    return hashlib.md5(code_phrase.encode('utf-8')).hexdigest() + '_' + name


def main():
    command = ''
    menu = '\nКоманды:\n1 - Добавить новый аккаунт\n2 - Удалить существующий аккаунт\n3 - Сбросить сообщение к образцу\n4 - Выход'
    accounts = list(json.loads(manager.bot.get_chat(chat_id=manager.chat).pinned_message.text).keys())
    while command != '4':
        available_msg(accounts)
        print(menu)
        command = input('Ввод: ')
        if command == '1':
            name = input('Имя, которое будет добавлено к хэшу (можно оставить пустым): ')
            hsh = generate_hash(name)
            manager.add_account(hsh)
            new_hash_print(hsh)
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
            print("Сообщение сброшено к изначальным настройкам.")


if __name__ == '__main__':
    main()
