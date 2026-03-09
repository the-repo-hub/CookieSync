from typing import Dict
import socket

class NoAccountException(Exception):
    pass

class AlreadyRegistered(Exception):
    pass

class Client:

    #todo мб стоит переместить на сервер, мы же там их регистрируем
    registered_clients: Dict[str, set] = {}

    def __init__(self, client_socket: socket.socket):
        self.socket = client_socket
        self.full_address = client_socket.getpeername()
        self.address, self.port = self.full_address
        self.hash = None
        self._registered = False

    def register(self) -> None:
        # эти проверки нужно сократить
        if not self.hash:
            raise NoAccountException()

        if self._registered:
            raise AlreadyRegistered()
        if not self.registered_clients.get(self.hash):
            self.registered_clients[self.hash] = set()
        self.registered_clients[self.hash].add(self)
        self._registered = True

    def unregister(self) -> None:
        if self.registered_clients.get(self.hash):
            self.registered_clients[self.hash].discard(self)
            self._registered = False

    def is_registered(self) -> bool:
        return self._registered
