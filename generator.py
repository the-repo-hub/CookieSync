from ResoBot import AccountManager

acc = AccountManager()


def available_msg():
    print('Сейчас на сервере доступны следующие аккаунты:\n')
    for num, hsh in enumerate(acc.accounts, start=1):
        print(f"{num}) {hsh}")


def new_hash_msg(hsh):
    answer = '\n' + '//' * 31
    answer += ('\n//' + ' ' * 58 + "\\\\") * 3
    answer += '\n//' + ' ' * 25 + 'Новый хэш:' + ' ' * 23 + "\\\\"
    answer += '\n//' + ' ' * 14 + hsh + ' ' * 12 + "\\\\"
    answer += ('\n//' + ' ' * 58 + "\\\\") * 3
    answer += '\n' + '//' * 31
    print(answer, end='\n\n')


def main():
    command = ''
    menu = '\nКоманды:\n1 - Добавить новый аккаунт\n2 - Удалить существующий аккаунт\n3 - Заменить существующий акканут новым\n4 - Выход'

    while command != '4':
        available_msg()
        print(menu)
        command = input('Ввод: ')

        if command == '1':
            name = input('Имя, которое будет добавлено к хэшу (можно оставить пустым): ')
            hsh = acc.generate_hash(name)
            acc[hsh] = acc.cookie_sample
            new_hash_msg(hsh)

        elif command == '2':
            command = input('Хэш, который необходимо удалить: ')
            if command in acc.accounts:
                acc.remove_account(command)
                print(f'Хэш {command} удалён.')
            else:
                print('Хэша нет в списке!')

        elif command == '3':
            command = input('Хэш, который необходимо заменить: ')
            if command in acc.accounts:
                cookie = acc[command]
                acc.remove_account(command)
                hsh = acc.generate_hash()
                acc[hsh] = cookie
                new_hash_msg(hsh)
            else:
                print('Хэша нет в списке!')


if __name__ == '__main__':
    main()
