from typing import Optional

def recv_data_or_none(conn, n) -> Optional[bytes]:
    data = b''
    while len(data) < n:
        try:
            chunk = conn.recv(n - len(data))
        except ConnectionResetError:
            return None
        if not chunk:
            return None
        data += chunk
    return data