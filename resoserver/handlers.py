def recv_data_or_none(conn, n):
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