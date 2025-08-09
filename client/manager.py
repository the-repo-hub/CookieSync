import json
import socket
from typing import Dict, List

from tenacity import retry, stop_after_attempt, retry_if_not_exception_type, wait_fixed

from resoserver.choices import Fields, Commands
from resoserver.handlers import recv_data_or_none
from src.exceptions import InvalidHash, CantConnectServer

class Manager(object):

    def __init__(self, server_addr: str, server_port: int):
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket.settimeout(10)
        try:
            self._socket.connect((server_addr, server_port))
        except TimeoutError:
            raise CantConnectServer
        except ConnectionRefusedError:
            raise CantConnectServer

    @retry(
        stop=stop_after_attempt(10),
        reraise=True,
        retry=retry_if_not_exception_type((InvalidHash, CantConnectServer)),
        wait=wait_fixed(1),
    )
    def _send_output(self, output) -> Dict:
        to_send = json.dumps(output).encode('utf-8')
        self._socket.sendall(len(to_send).to_bytes(4, 'big') + to_send)
        length = int.from_bytes(recv_data_or_none(self._socket, 4), 'big')
        if not length:
            raise CantConnectServer
        data = recv_data_or_none(self._socket, length)
        data = json.loads(data.decode())
        return data

    def get_cookies(self, hsh: str) -> List[Dict]:
        output = {
            Fields.command: Commands.get,
            Fields.hash: hsh,
        }
        result = self._send_output(output)
        if result[Fields.result] is False:
            raise InvalidHash(InvalidHash.msg.format(hash=hsh))
        return result.get(Fields.cookies)

    def set_cookies(self, cookies: List, hsh: str) -> None:
        output = {
            Fields.command: Commands.set,
            Fields.hash: hsh,
            Fields.cookies: cookies,
        }
        result = self._send_output(output)
        if result[Fields.result] is False:
            raise InvalidHash(InvalidHash.msg.format(hash=hsh))

    def add_account(self, hsh: str) -> None:
        output = {
            Fields.command: Commands.create,
            Fields.hash: hsh,
        }
        self._send_output(output)

    def remove_account(self, hsh: str) -> None:
        output = {
            Fields.command: Commands.delete,
            Fields.hash: hsh,
        }
        result = self._send_output(output)
        if result[Fields.result] is False:
            raise InvalidHash(InvalidHash.msg.format(hash=hsh))

    def get_all_accounts(self) -> List[str]:
        output = {
            Fields.command: Commands.get_all,
        }
        result = self._send_output(output)
        return result.get(Fields.message)
