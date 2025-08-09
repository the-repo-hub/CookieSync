"""Console for manage pinned message."""

from typing import List

from client.manager import Manager
from src.settings import SERVER_ADDRESS, SERVER_PORT


class Console(object):
    """Pinned message console class."""

    manager = Manager(SERVER_ADDRESS, SERVER_PORT)
    accounts: List

    def command_handler(self, command: str) -> None:
        """Command cycle handler.

        Args:
            command: stringify num of option
        """
        if command == '1':
            name = input('Название аккаунта: ')
            self.manager.add_account(name)
            print('Новый аккаунт: {hsh}'.format(hsh=name), end='\n\n')
            self.accounts.append(name)

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
        return True

if __name__ == '__main__':
    Console().main()
