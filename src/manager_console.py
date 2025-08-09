"""Console for manage pinned message."""

from random import getrandbits
from typing import List

from client.manager import Manager
from src.exceptions import MessageTooLong
from src.settings import SERVER_ADDRESS, SERVER_PORT


class Console(object):
    """Pinned message console class."""

    manager = Manager(SERVER_ADDRESS, SERVER_PORT)
    bits = 128
    accounts: List

    def command_handler(self, command: str) -> None:
        """Command cycle handler.

        Args:
            command: stringify num of option
        """
        if command == '1':
            name = input('Имя, которое будет добавлено к хэшу (можно оставить пустым): ')
            hsh = '{hash}_{name}'.format(hash=str(getrandbits(self.bits)), name=name)
            try:
                self.manager.add_account(hsh)
            except MessageTooLong:
                print(MessageTooLong.msg)
            else:
                print('Новый хэш: {hsh}'.format(hsh=hsh), end='\n\n')
                self.accounts.append(hsh)

        elif command == '2':
            if not self.accounts:
                print('Нет хэшей на сервере')
                return
            num = int(input('Номер хэша, который необходимо удалить: ')) - 1
            hsh = self.accounts[num]
            if hsh in self.accounts:
                self.manager.remove_account(hsh)
                self.accounts.pop(num)
                print('Хэш {hsh} удалён.'.format(hsh=hsh))
            else:
                print('Хэша нет в списке!')

    def main(self) -> None:
        """Console execution."""
        self.accounts = self.manager.get_all_accounts()
        command = ''
        menu = '\nКоманды:\n1 - Добавить новый аккаунт\n2 - Удалить существующий аккаунт\n3 - Выход'

        while command != '3':
            self._available_accounts_print()
            print(menu)
            command = input('Ввод: ')
            self.command_handler(command)

    def _available_accounts_print(self) -> None:
        """Available message print function."""
        print('Сейчас на сервере доступны следующие аккаунты:\n')
        for num, hsh in enumerate(self.accounts, start=1):
            print('{num}) {hsh}'.format(num=num, hsh=hsh))

    def __exit__(self, exc_type, exc_val, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            return True

if __name__ == '__main__':
    Console().main()
