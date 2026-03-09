import os
import logging
from logging.handlers import MemoryHandler
from logging import getLogger

def get_logger():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    mem_handler = MemoryHandler(capacity=100, target=logging.StreamHandler())
    server_logger = getLogger('ResoServer')
    server_logger.addHandler(mem_handler)
    return server_logger

SRC_PATH = os.path.dirname(__file__)
COOKIE_SERVER_PATH = os.path.abspath(os.path.join(SRC_PATH, '..'))
ACCOUNTS_PATH = os.path.join(COOKIE_SERVER_PATH, 'accounts')
KEYS_PATH = os.path.join(COOKIE_SERVER_PATH, 'keys')
SERVER_LOGGER = get_logger()
COOKIE_TIMEOUT = 60
ENCODING = 'utf-8'
