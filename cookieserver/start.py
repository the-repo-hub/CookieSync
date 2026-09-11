import argparse
import asyncio

from cookieserver.src.server import Server
import logging

logging.basicConfig(level=logging.INFO)


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
    srv = Server(args.host, args.port)

    async def run():
        await srv.start()
        try:
            await srv.wait_closed()
        except asyncio.CancelledError:
            pass
        finally:
            await srv.stop()

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    main()
