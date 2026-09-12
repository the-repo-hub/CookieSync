import argparse
import asyncio

from cookieserver.src.server import Server
from cookieserver.src.settings import HOST, PORT, configure_logging

configure_logging('INFO')


def main():
    parser = argparse.ArgumentParser(
        description="Reso socket server for accounts"
    )
    host = HOST
    port = PORT
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

    parser.add_argument(
        "--no-tls",
        action="store_true",
        help="Run without TLS (ws:// instead of wss://)"
    )

    args = parser.parse_args()
    srv = Server(args.host, args.port, use_tls=not args.no_tls)

    try:
        asyncio.run(srv.run())
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    main()
