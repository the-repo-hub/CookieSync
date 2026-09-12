import configparser
import logging
import os

logger = logging.getLogger(__name__)

SRC_PATH = os.path.dirname(__file__)
COOKIE_SERVER_PATH = os.path.abspath(os.path.join(SRC_PATH, '..'))
SERVER_CONFIG_PATH = os.path.join(COOKIE_SERVER_PATH, 'server_config.conf')
ACCOUNTS_PATH = os.path.join(COOKIE_SERVER_PATH, 'accounts')
KEYS_PATH = os.path.join(COOKIE_SERVER_PATH, 'keys')

_config = configparser.ConfigParser()
if not _config.read(SERVER_CONFIG_PATH, encoding='utf-8'):
    logger.warning(f"Config file {SERVER_CONFIG_PATH} not found, using defaults")

# Все параметры конфигурации находятся в одной секции [server].
HOST = _config.get('server', 'host', fallback='0.0.0.0')
PORT = _config.getint('server', 'port', fallback=52314)
PING_INTERVAL = _config.getint('server', 'ping_interval', fallback=30)
PING_TIMEOUT = _config.getint('server', 'ping_timeout', fallback=10)

# TLS: пути к сертификату и ключу. Можно указывать сертификаты, выданные CA
# (например, Let's Encrypt fullchain.pem / privkey.pem) — тогда клиенты-браузеры
# доверят wss://-подключению без ручного импорта.
CERT_PATH = os.path.abspath(
    _config.get('server', 'cert', fallback=os.path.join(KEYS_PATH, 'cert.pem'))
)
KEY_PATH = os.path.abspath(
    _config.get('server', 'key', fallback=os.path.join(KEYS_PATH, 'key.pem'))
)

COOKIE_TIMEOUT = _config.getint('server', 'cookie_timeout', fallback=60)
MAX_SIZE = _config.getint('server', 'max_size', fallback=1024)
ENCODING = _config.get('server', 'encoding', fallback='utf-8')
LOG_LEVEL = _config.get('server', 'log_level', fallback='INFO').upper()

LOG_FORMAT = '%(asctime)s %(levelname)s %(name)s: %(message)s'
LOG_DATE_FORMAT = '%Y-%m-%d %H:%M:%S'


def configure_logging(level: str = LOG_LEVEL) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format=LOG_FORMAT,
        datefmt=LOG_DATE_FORMAT,
    )