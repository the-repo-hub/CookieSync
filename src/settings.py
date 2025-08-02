"""Settings module."""

import os

from dotenv import load_dotenv

load_dotenv()
BOT_TOKEN = os.environ.get('BOT_TOKEN')
CHAT_ID = os.environ.get('CHAT_ID')
TELEGRAM_MSG_LIMIT = 4096

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
INI_PATH = os.path.join(BASE_DIR, 'reso.ini')