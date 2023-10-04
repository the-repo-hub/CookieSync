"""Console for manage pinned message."""

import json
import unittest
from random import getrandbits
from reso_auto.manager import MessageManager
from reso_auto.tests.tests import ResoTestCase


class Console:
    """Pinned message console class."""

    manager = MessageManager()
    BITS = 128
    if not manager.bot.get_chat(chat_id=manager.chat).pinned_message:
        manager.reinit()
    accounts = list(json.loads(manager.bot.get_chat(chat_id=manager.chat).pinned_message.text).keys())

    @classmethod
    def _available_accounts_print(cls) -> None:
        """Available message print function."""
        print('Сейчас на сервере доступны следующие аккаунты:\n')
        for num, hsh in enumerate(cls.accounts, start=1):
            print(f'{num}) {hsh}')

    @classmethod
    def main(cls) -> None:
        """Main console function."""
        command = ''
        menu = '\nКоманды:\n1 - Добавить новый аккаунт\n2 - Удалить существующий аккаунт\n3 - Сбросить сообщение к изначальным настройкам\n4 - Запуск тесткейсов\n5 - Выход'

        while command != '5':
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
            elif command == '4':
                suite = unittest.TestLoader().loadTestsFromTestCase(testCaseClass=ResoTestCase)
                unittest.TextTestRunner().run(suite)
                continue


if __name__ == '__main__':
    Console.main()
