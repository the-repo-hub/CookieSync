#!/usr/bin/env python
import argparse
import asyncio
import logging
import os
import sys
from typing import List

from cookieserver.src.errors import StorageError
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
    name = ""
    help = ""

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        pass

    def handle(self, args: argparse.Namespace) -> None:
        raise NotImplementedError


class RunServerCommand(BaseCommand):
    name = "runserver"
    help = "Start the WebSocket cookie server"

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
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
        return Server(
            args.host,
            args.port,
            use_tls=not args.no_tls,
            certfile=args.cert or (CERT_PATH if not args.no_tls else None),
            keyfile=args.key or (KEY_PATH if not args.no_tls else None),
        )

    def handle(self, args: argparse.Namespace) -> None:
        configure_logging(LOG_LEVEL)
        server = self.build_server(args)
        try:
            asyncio.run(server.run())
        except KeyboardInterrupt:
            pass


class CreateAccountCommand(BaseCommand):
    name = "create_account"
    help = "Create a new account"

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("name")

    def handle(self, args: argparse.Namespace) -> None:
        storage = AccountStorage()
        if storage.get_account(args.name):
            raise SystemExit(f"Error: account '{args.name}' already exists")
        storage.add_account(args.name)
        print(f"Account '{args.name}' created")


class ListAccountsCommand(BaseCommand):
    name = "list_accounts"
    help = "List existing accounts"

    def handle(self, args: argparse.Namespace) -> None:
        storage = AccountStorage()
        accounts = storage.get_all_accounts()
        if not accounts:
            print("No accounts")
            return
        for name in sorted(accounts):
            print(name)


class RemoveAccountCommand(BaseCommand):
    name = "remove_account"
    help = "Remove an account"

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("name")

    def handle(self, args: argparse.Namespace) -> None:
        storage = AccountStorage()
        try:
            storage.remove_account(args.name)
        except StorageError as e:
            raise SystemExit(f"Error: {e}")
        print(f"Account '{args.name}' removed")


class HelpCommand(BaseCommand):
    name = "help"
    help = "Show available commands"

    def handle(self, args: argparse.Namespace) -> None:
        build_parser().print_help()


COMMANDS: List[BaseCommand] = [
    RunServerCommand(),
    CreateAccountCommand(),
    ListAccountsCommand(),
    RemoveAccountCommand(),
    HelpCommand(),
]


def build_parser() -> argparse.ArgumentParser:
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
    args = build_parser().parse_args(argv if argv is not None else sys.argv[1:])
    args.handler(args)


if __name__ == "__main__":
    main()