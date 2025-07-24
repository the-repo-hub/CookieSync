"""Settings module."""

import os

from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INI_FILE_PATH = os.path.join(BASE_DIR, 'reso.ini')
MESSAGE_SAMPLE_PATH=os.path.join(BASE_DIR, 'message_sample.json')
load_dotenv()
BOT_TOKEN = os.environ.get('BOT_TOKEN')
CHAT_ID = os.environ.get('CHAT_ID')
