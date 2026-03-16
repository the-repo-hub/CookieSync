import os

SRC_PATH = os.path.dirname(__file__)
COOKIE_SERVER_PATH = os.path.abspath(os.path.join(SRC_PATH, '..'))
ACCOUNTS_PATH = os.path.join(COOKIE_SERVER_PATH, 'accounts')
KEYS_PATH = os.path.join(COOKIE_SERVER_PATH, 'keys')
COOKIE_TIMEOUT = 60
ENCODING = 'utf-8'
