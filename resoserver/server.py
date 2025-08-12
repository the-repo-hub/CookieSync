import json
import logging
import os
import socket
import ssl
from functools import cached_property
from logging import getLogger
from logging.handlers import MemoryHandler
from threading import Thread
from typing import Dict, Tuple, Optional, Set

from resoserver.choices import Commands, Fields
from resoserver.handlers import recv_data_or_none

# то, что приходит
# {
#     'command': 'set',
#     'hash': 2312234,
#     'cookies': {}
# }

class Server:

    BASE_DIR = os.path.dirname(__file__)
    ACCOUNTS_PATH = os.path.join(BASE_DIR, 'accounts')
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    MAX_CHUNK = 1024
    mem_handler = MemoryHandler(capacity=100, target=logging.StreamHandler())
    server_logger = getLogger('ResoServer')
    server_logger.addHandler(mem_handler)

    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
        # {123456_test: {'aspnet': 'dfsdfssd'}}
        self._accounts: Dict[str, Dict] = {}
        self._active_clients: Dict[str, Set[socket.socket]] = {}
        self._init_accounts()
        self.socket = None
        self._init_socket()
        self.server_logger.info(f'Server listening on {self.host}:{self.port}')
        # {123456_test: {clientSocket1, clientSocket2}}

    def _init_accounts(self):
        for filename in os.listdir(self.ACCOUNTS_PATH):
            hsh = filename.split('.')[0]
            file = open(os.path.join(self.ACCOUNTS_PATH, filename))
            self._accounts[hsh] = json.loads(file.read())
            self._active_clients[hsh] = set()
            file.close()

    def _init_socket(self):
        _socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        _socket.setsockopt(
            socket.SOL_SOCKET,  # Уровень сокета
            socket.SO_REUSEADDR,  # Разрешить переиспользование адреса
            1  # Включить (1 = True)
        )
        _socket.bind((self.host, self.port))
        _socket.listen(50)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(
            certfile=os.path.join(self.BASE_DIR, 'cert.pem'),
            keyfile=os.path.join(self.BASE_DIR, 'key.pem'),
        )
        self.socket = context.wrap_socket(_socket, server_side=True)

    @cached_property
    def cookie_sample(self) -> Dict:
        path = os.path.join(self.BASE_DIR, 'cookie_sample.json')
        with open(path) as f:
            return json.loads(f.read())

    def _commit(self, hsh):
        filename = f'{hsh}.json'
        full_path = os.path.join(self.ACCOUNTS_PATH, filename)
        with open(full_path, 'w') as f:
            f.write(
                json.dumps(self._accounts[hsh])
            )

    def _send_cookies_to_clients(self, hsh: str, client_address: Tuple):
        for client_socket in self._active_clients[hsh]:
            if client_socket.getpeername() == client_address:
                continue
            output = {
                Fields.command: Commands.set,
                Fields.cookies: self._accounts[hsh],
            }
            output_json = json.dumps(output).encode('utf-8')
            client_socket.sendall(len(output_json).to_bytes(4, 'big') + output_json)

    def _get_bytes_output(self,client_address: Tuple, hsh: str, json_data: Dict) -> Optional[bytes]:
        command = json_data.get(Fields.command)
        if not command:
            self.server_logger.info(f'Client {client_address[0]}:{client_address[1]} no command found')
            return None
        self.server_logger.info(f'Command received: {command}')
        if command == Commands.create:
            self._accounts[hsh] = self.cookie_sample
            self._commit(hsh)
            output = {
                Fields.result: True,
                Fields.message: 'Cookies was created successfully',
            }
        elif command == Commands.get_all:
            output = {
                Fields.result: True,
                Fields.message: list(self._accounts.keys()),
            }
        elif hsh not in self._accounts:
            output = {
                Fields.result: False,
                Fields.message: 'Hash was not found in storage',
            }
        elif command == Commands.register:
            output = {
                Fields.result: True,
                Fields.message: f'Client {client_address[0]}:{client_address[1]} registered successfully',
                Fields.cookies: self._accounts[hsh],
            }
        elif command == Commands.get:
            output = {
                Fields.result: True,
                Fields.cookies: self._accounts[hsh],
            }
        elif command == Commands.set:
            cookies = json_data.get(Fields.cookies)
            if not cookies:
                self.server_logger.info(f'Client {client_address[0]}:{client_address[1]} cookies not found')
                return None
            self._accounts[hsh] = json_data.get(Fields.cookies)
            self._commit(hsh)
            output = {
                Fields.result: True,
                Fields.message: 'Cookies was set successfully',
            }
            # self._send_cookies_to_clients(hsh)
        elif command == Commands.delete:
            self._accounts.pop(hsh)
            self._active_clients.pop(hsh)
            filename = f'{hsh}.json'
            full_path = os.path.join(self.ACCOUNTS_PATH, filename)
            os.remove(full_path)
            output = {
                Fields.result: True,
                Fields.message: 'Cookies was deleted successfully',
            }
        else:
            output = {
                Fields.result: False,
                Fields.message: 'Invalid command',
            }
        return json.dumps(output).encode('utf-8')

    def __handle_client(self, client_socket, client_address):
        self.server_logger.info(f'Client connected: {client_address[0]}:{client_address[1]}')
        hsh = None
        while True:
            length_bytes = recv_data_or_none(client_socket, 4)
            if not length_bytes:
                break
            length = int.from_bytes(length_bytes, 'big')
            if length > self.MAX_CHUNK:
                self.server_logger.info(f'Client {client_address[0]}:{client_address[1]} loaded too many chunks')
                break
            data = recv_data_or_none(client_socket, length)
            if not data:
                break
            try:
                json_data = json.loads(data.decode('utf-8'))
            except json.JSONDecodeError:
                self.server_logger.info(f'Client {client_address[0]}:{client_address[1]} sent invalid JSON')
                break
            # self._active_clients[hsh].add(client_socket)
            # может быть строкой и нан
            hsh = json_data.get(Fields.hash)
            if hsh:
                if not self._active_clients.get(hsh):
                    self._active_clients[hsh] = set()
                self._active_clients[hsh].add(client_socket)
            bytes_output = self._get_bytes_output(client_address, hsh, json_data)
            if not bytes_output:
                break
            client_socket.sendall(len(bytes_output).to_bytes(4, 'big') + bytes_output)
            self.server_logger.info(f'Response sent: {bytes_output}')
        client_socket.close()
        if hsh:
            self._active_clients[hsh].remove(client_socket)
        self.server_logger.info(f'Client {client_address[0]}:{client_address[1]} socket closed')

    def run(self):
        # каждое новое подключение (одно приложение)
        while True:
            try:
                client_socket, client_address = self.socket.accept()
            except ssl.SSLEOFError:
                # клиент сокет убит до того, как обменяться данными
                continue
            Thread(target=self.__handle_client, args=(client_socket, client_address), daemon=True).start()

    def start(self):
        try:
            self.run()
        except KeyboardInterrupt:
            pass
        finally:
            self.server_logger.info('Server shutting down...')
            self.socket.close()
