"""Settings module."""

import os

from dotenv import load_dotenv
import sys

def get_base_dir():
    """Определяет корневую папку приложения, учитывая PyInstaller."""

    if getattr(sys, 'frozen', False):
        # Если запущен .exe, берем папку, где он лежит
        return os.path.dirname(sys.executable)
    else:
        # Обычный запуск Python-скрипта
        return os.path.abspath(os.path.dirname(__file__))

load_dotenv()
BOT_TOKEN = os.environ.get('BOT_TOKEN')
CHAT_ID = os.environ.get('CHAT_ID')
TELEGRAM_MSG_LIMIT = 4096
BASE_DIR = get_base_dir()
INI_PATH = os.path.join(BASE_DIR, 'reso.ini')