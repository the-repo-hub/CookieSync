from typing import Dict
import socket

class NoHashException(Exception):
    pass

class Client:

    registered_clients: Dict[str, set] = {}

    def __init__(self, client_socket: socket.socket):
        self.socket = client_socket
        self.full_address = client_socket.getpeername()
        self.address, self.port = self.full_address
        self.hash = None
        self.registered = False

    def register(self) -> None:
        if not self.hash:
            raise NoHashException
        if not self.registered_clients.get(self.hash):
            self.registered_clients[self.hash] = set()
        self.registered_clients[self.hash].add(self)
        self.registered = True

    def unregister(self) -> None:
        if self.registered_clients.get(self.hash):
            self.registered_clients[self.hash].discard(self)
            self.registered = False
