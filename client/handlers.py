from typing import Optional


def recv_data_or_none(conn, n) -> Optional[bytes]:
    data = b''
    while len(data) < n:
        try:
            chunk = conn.recv(n - len(data))
        except ConnectionResetError:
            # сервер упал
            exit(0)
        if not chunk:
            # сервер закрыл соединение
            exit(0)
        data += chunk
    return data