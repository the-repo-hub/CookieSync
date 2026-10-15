#!/usr/bin/env python
"""CLI для запуска CookieServer и просмотра аккаунтов без изменения их файлов."""

import argparse
import asyncio
import os
import sys
from typing import List

from cookieserver.src.server import Server
from cookieserver.src.settings import (
    CERT_PATH,
    HOST,
    KEY_PATH,
    LOG_LEVEL,
    PORT,
    configure_logging,
)
from cookieserver.src.storage import AccountStorage


class BaseCommand:
    """Интерфейс CLI-команды с именем, справкой и необязательными аргументами."""

    name = ""
    help = ""

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        """Дополняет парсер команды; по умолчанию дополнительных аргументов нет."""
        pass

    def handle(self, args: argparse.Namespace) -> None:
        """Выполняет команду с разобранными аргументами; реализуется наследниками."""
        raise NotImplementedError


class RunServerCommand(BaseCommand):
    """Запуск WebSocket-сервера с возможностью переопределить адрес и TLS."""

    name = "runserver"
    help = "Start the WebSocket cookie server"

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        """Добавляет адрес, порт, отключение TLS и пути сертификата и ключа."""
        parser.add_argument("--host", type=str, default=HOST)
        parser.add_argument("--port", type=int, default=PORT)
        parser.add_argument(
            "--no-tls", action="store_true", help="run without TLS (ws://)"
        )
        parser.add_argument(
            "--cert", type=str, default=None,
            help="Path to the TLS certificate (PEM). Defaults to server_config.conf [server] cert.",
        )
        parser.add_argument(
            "--key", type=str, default=None,
            help="Path to the TLS private key (PEM). Defaults to server_config.conf [server] key.",
        )

    def build_server(self, args: argparse.Namespace) -> Server:
        """Создаёт сервер из CLI-аргументов и настроек по умолчанию без запуска."""
        return Server(
            args.host,
            args.port,
            use_tls=not args.no_tls,
            certfile=args.cert or (CERT_PATH if not args.no_tls else None),
            keyfile=args.key or (KEY_PATH if not args.no_tls else None),
        )

    def handle(self, args: argparse.Namespace) -> None:
        """Настраивает журнал и запускает event loop до остановки сервера."""
        configure_logging(LOG_LEVEL)
        server = self.build_server(args)
        try:
            asyncio.run(server.run())
        except KeyboardInterrupt:
            pass


class ListAccountsCommand(BaseCommand):
    """Просмотр имён аккаунтов без очистки или перезаписи их файлов."""

    name = "list_accounts"
    help = "List existing accounts"

    def handle(self, args: argparse.Namespace) -> None:
        """Печатает отсортированные имена загружаемых аккаунтов либо No accounts."""
        storage = AccountStorage(cleanup_on_load=False)
        accounts = storage.get_all_accounts()
        if not accounts:
            print("No accounts")
            return
        for name in sorted(accounts):
            print(name)


class HelpCommand(BaseCommand):
    """Вывод справки по всем зарегистрированным CLI-командам."""

    name = "help"
    help = "Show available commands"

    def handle(self, args: argparse.Namespace) -> None:
        """Печатает справку общего парсера."""
        build_parser().print_help()


COMMANDS: List[BaseCommand] = [
    RunServerCommand(),
    ListAccountsCommand(),
    HelpCommand(),
]


def build_parser() -> argparse.ArgumentParser:
    """Создаёт парсер подкоманд, связывая каждую с её методом handle."""
    program = os.path.basename(sys.argv[0]) if sys.argv else "manage.py"
    parser = argparse.ArgumentParser(
        prog=program,
        description="CookieSync management utility",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    for command in COMMANDS:
        sub = subparsers.add_parser(command.name, help=command.help, description=command.help)
        command.add_arguments(sub)
        sub.set_defaults(handler=command.handle)

    return parser


def main(argv: List[str] = None) -> None:
    """Выполняет CLI; argv не включает имя программы, None использует sys.argv."""
    args = build_parser().parse_args(argv if argv is not None else sys.argv[1:])
    args.handler(args)


if __name__ == "__main__":
    main()
