import json
import logging
import os
import socket
from functools import cached_property
from logging import getLogger
from logging.handlers import MemoryHandler
from threading import Thread
from typing import Dict

from resoserver.choices import Commands, Fields
from resoserver.handlers import recv_data_or_none
# то, что приходит
# {
#     'command': 'set',
#     'hash': 2312234,
#     'cookies': {}
# }

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
mem_handler = MemoryHandler(capacity=100, target=logging.StreamHandler())
server_logger = getLogger('ResoServer')
server_logger.addHandler(mem_handler)

class Server:

    BASE_DIR = os.path.dirname(__file__)
    ACCOUNTS_PATH = os.path.join(BASE_DIR, 'accounts')

    def __init__(self, host='0.0.0.0', port=9999):
        self.host = host
        self.port = port
        # {123456_test: {'aspnet': 'dfsdfssd'}}
        self._accounts = {}
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.setsockopt(
            socket.SOL_SOCKET,  # Уровень сокета
            socket.SO_REUSEADDR,  # Разрешить переиспользование адреса
            1  # Включить (1 = True)
        )
        self.socket.bind((self.host, self.port))
        self.socket.listen(100)
        for filename in os.listdir(self.ACCOUNTS_PATH):
            hsh = filename.split('.')[0]
            file = open(os.path.join(self.ACCOUNTS_PATH, filename))
            self._accounts[hsh] = json.loads(file.read())
            # self._active_clients[hsh] = set()
            file.close()
        server_logger.info(f'Server listening on {self.host}:{self.port}')
        # {123456_test: {clientSocket1, clientSocket2}}
        # self._active_clients = {}

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

    # def _send_cookies_to_clients(self, hsh):
    #     for client_socket in self._active_clients[hsh]:
    #         output = {
    #             Fields.command: Commands.set,
    #             Fields.cookies: self._accounts[hsh],
    #         }
    #         output_json = json.dumps(output).encode('utf-8')
    #         client_socket.sendall(len(output_json).to_bytes(4, 'big') + output_json)

    def _get_bytes_output(self, hsh, data):
        if data.get(Fields.command) == Commands.create:
            self._accounts[hsh] = self.cookie_sample
            self._commit(hsh)
            output = {
                Fields.result: True,
                Fields.message: 'Cookies was created successfully',
            }
        elif data.get(Fields.command) == Commands.get_all:
            output = {
                Fields.result: True,
                Fields.message: list(self._accounts.keys()),
            }
        elif hsh not in self._accounts:
            output = {
                Fields.result: False,
                Fields.message: 'Hash was not found in storage',
            }
        elif data.get(Fields.command) == Commands.get:
            output = {
                Fields.result: True,
                Fields.cookies: self._accounts[hsh],
            }
        elif data.get(Fields.command) == Commands.set:
            self._accounts[hsh] = data.get(Fields.cookies)
            self._commit(hsh)
            output = {
                Fields.result: True,
                Fields.message: 'Cookies was set successfully',
            }
            # self._send_cookies_to_clients(hsh)
        elif data.get(Fields.command) == Commands.delete:
            self._accounts.pop(hsh)
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
        server_logger.info(f'Client connected: {client_address[0]}:{client_address[1]}')
        while True:
            length_bytes = recv_data_or_none(client_socket, 4)
            if not length_bytes:
                break
            length = int.from_bytes(length_bytes, 'big')
            data = recv_data_or_none(client_socket, length)
            if not data:
                break
            data = json.loads(data.decode('utf-8'))
            server_logger.info(f'Command received: {data.get(Fields.command)}')
            hsh = data.get(Fields.hash)
            # self._active_clients[hsh].add(client_socket)
            bytes_output = self._get_bytes_output(hsh, data)
            client_socket.sendall(len(bytes_output).to_bytes(4, 'big') + bytes_output)
            server_logger.info(f'Response sent: {bytes_output}')
        client_socket.close()
        # self._active_clients[hsh].pop(client_socket)
        server_logger.info(f'Client {client_address[0]}:{client_address[1]} socket closed')

    def run(self):
        # каждое новое подключение (одно приложение)
        while True:
            client_socket, client_address = self.socket.accept()
            Thread(target=self.__handle_client, args=(client_socket, client_address), daemon=True).start()


if __name__ == '__main__':
    server = Server()
    try:
        server.run()
    except KeyboardInterrupt:
        pass
    finally:
        server_logger.info('Server shutting down...')
        server.socket.close()
