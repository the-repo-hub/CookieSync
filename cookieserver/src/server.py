import json
import socket
import ssl
from threading import Thread
from typing import Dict, Optional, Type

from cookieserver.src.choices import Commands, Fields
from cookieserver.src.client import Client
from cookieserver.src.commands import Command, GetAllAccountsCommand, RegisterCommand, SetCookiesCommand, DeleteCommand, \
    CreateCookiesCommand, GetCookiesCommand
from cookieserver.src.handlers import recv_data_or_none
from cookieserver.src.settings import SERVER_LOGGER, ENCODING
from cookieserver.src.storage import CookieStorage


class Server:

    MAX_CHUNK = 1024
    #todo убрать
    commands: Dict[str, Type[Command]] = {
        Commands.get_all: GetAllAccountsCommand(),
        Commands.create: CreateCookiesCommand(),
        Commands.register: RegisterCommand(),
        Commands.delete: DeleteCommand(),
        Commands.set: SetCookiesCommand(),
        Commands.get: GetCookiesCommand(),
    }

    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
        self.socket = None
        self._init_socket()
        self._cookie_storage = CookieStorage()
        self._running = False

    def _init_socket(self):
        _socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        _socket.setsockopt(
            socket.SOL_SOCKET,  # Socket level
            socket.SO_REUSEADDR,  # Allow address reuse
            1,
        )
        _socket.bind((self.host, self.port))
        _socket.listen(10)
        _socket.settimeout(1)
        self.socket = _socket
        # context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        # context.load_cert_chain(
        #     certfile=os.path.join(KEYS_PATH, 'cert.pem'),
        #     keyfile=os.path.join(KEYS_PATH, 'key.pem'),
        # )
        # context.minimum_version = ssl.TLSVersion.TLSv1_2
        # self.socket = context.wrap_socket(_socket, server_side=True)

    def _get_output(self, client: Client, json_data: Dict) -> Dict:
        command = json_data.get(Fields.command)
        if not command:
            SERVER_LOGGER.info(f'Client {client.full_address} no command found')
            return {
                Fields.result: False,
                Fields.message: f'You must specify a {Fields.command} field in request',
            }
        SERVER_LOGGER.info(f'From client {client.full_address}\nCommand received: {command}')
        client.hash = json_data.get(Fields.hash)
        command_instance = self.commands.get(command)
        if not command_instance:
            SERVER_LOGGER.info(f'Client {client.full_address} sent invalid command {command}')
            return {
                Fields.result: False,
                Fields.message: f'{command} is invalid command',
            }
        result = command_instance.execute(
            storage=self._cookie_storage,
            client=client,
            json_data=json_data
        )
        result[Fields.request_id] = json_data.get(Fields.request_id)
        return result

    def _get_json_data(self, client: Client) -> Optional[Dict]:
        """
        Syntax parsing incoming JSON data. If invalid, returns None.
        """
        # todo убрать наны
        try:
            length_bytes = recv_data_or_none(client.socket, 4)
        except ssl.SSLError as e:
            SERVER_LOGGER.info(f'Client {client.full_address} SSL error {e}')
            return None
        if not length_bytes:
            return None
        length = int.from_bytes(length_bytes, 'big')
        if length > self.MAX_CHUNK:
            SERVER_LOGGER.info(f'Client {client.full_address} loaded too many chunks')
            return None
        try:
            data = recv_data_or_none(client.socket, length)
        except ssl.SSLError as e:
            SERVER_LOGGER.info(f'Client {client.full_address} SSL error {e}')
            return None
        if not data:
            return None
        try:
            return json.loads(data.decode(ENCODING))
        except UnicodeDecodeError:
            SERVER_LOGGER.info(f'Client {client.full_address} decode error')
            return None
        except json.JSONDecodeError:
            SERVER_LOGGER.info(f'Client {client.full_address} sent invalid JSON')
            return None

    def _handle_client(self, client: Client):
        """
        Handle a client connection.
        """
        SERVER_LOGGER.info(f'Client connected: {client.full_address}')
        while True:
            json_data = self._get_json_data(client)
            if not json_data:
                break
            output = self._get_output(client, json_data)
            bytes_output = json.dumps(output).encode(ENCODING)
            # todo а если клиент в это время отключится?
            # нужно обработать исключение для sendall
            client.socket.sendall(len(bytes_output).to_bytes(4, 'big') + bytes_output)
        client.unregister()
        client.socket.close()
        SERVER_LOGGER.info(f'Client {client.full_address} connection closed')

    def start(self):
        # каждое новое подключение (одно приложение)
        SERVER_LOGGER.info(f'Server listening on {self.host}:{self.port}')
        self._running = True
        while self._running:
            try:
                client_socket, client_address = self.socket.accept()
            except ssl.SSLEOFError:
                # клиент сокет убит до того, как обменяться данными
                SERVER_LOGGER.error('Client disconnected before key sharing')
            except ssl.SSLZeroReturnError:
                # nmap
                SERVER_LOGGER.error('Cant establish SSL connection')
            except ssl.SSLError:
                # прочее
                SERVER_LOGGER.error('Unknown SSL error')
            except KeyboardInterrupt:
                SERVER_LOGGER.info('Server is shutting down...')
                self.stop()
                break
            except ConnectionResetError:
                # nmap
                SERVER_LOGGER.error('Connection reset by peer')
            except socket.timeout:
                continue
            except Exception as e:
                SERVER_LOGGER.error(f'Unknown exception: {e}')
            else:
                client = Client(client_socket)
                Thread(target=self._handle_client, args=(client,), daemon=True).start()

    def stop(self):
        self._running = False
        self.socket.shutdown(socket.SHUT_WR)
