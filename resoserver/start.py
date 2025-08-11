import argparse
from resoserver.server import Server

def main():
    parser = argparse.ArgumentParser(
        description="Reso socket server for accounts"
    )
    host = "0.0.0.0"
    port = 52314
    parser.add_argument(
        "--host",
        type=str,
        default=host,
        help=f"IP address or hostname where the server will run (default: {host})"
    )

    parser.add_argument(
        "--port",
        type=int,
        default=port,
        help=f"Port where the server will run (default: {port})"
    )

    args = parser.parse_args()
    server = Server(args.host, args.port)
    try:
        server.run()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_logger.info('Server shutting down...')
        server.socket.close()

if __name__ == "__main__":
    main()
