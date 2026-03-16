from asyncio import StreamWriter


class Client:

    def __init__(self, writer: StreamWriter) -> None:
        self.writer = writer
        self.full_address = writer.get_extra_info('peername')
        self.address, self.port = self.full_address

    def __hash__(self):
        return hash(self.writer)

    def __eq__(self, other):
        if not isinstance(other, Client):
            return False
        return self.writer is other.writer
