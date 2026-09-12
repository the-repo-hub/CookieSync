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

HOST = _config.get('server', 'host', fallback='0.0.0.0')
PORT = _config.getint('server', 'port', fallback=52314)
PING_INTERVAL = _config.getint('server', 'ping_interval', fallback=30)
PING_TIMEOUT = _config.getint('server', 'ping_timeout', fallback=10)
COOKIE_TIMEOUT = _config.getint('storage', 'cookie_timeout', fallback=60)
MAX_SIZE = _config.getint('storage', 'max_size', fallback=1024)
ENCODING = _config.get('storage', 'encoding', fallback='utf-8')
LOG_LEVEL = _config.get('logging', 'level', fallback='INFO').upper()