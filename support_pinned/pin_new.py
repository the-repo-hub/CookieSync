import os

import dotenv
from telebot import TeleBot

dotenv.load_dotenv()

TOKEN = os.environ.get('BOT_TOKEN')
CHAT_ID = os.environ.get('CHAT_ID')
bot = TeleBot(TOKEN)

text = bot.get_chat(CHAT_ID).pinned_message.text
if not text:
    current_path = os.path.abspath(os.path.dirname(__file__))
    with open(os.path.join(current_path, 'cookies_sample.json'), 'r') as f:
        text = f.read()
m = bot.send_message(CHAT_ID, text, disable_notification=True)
bot.pin_chat_message(CHAT_ID, m.message_id, disable_notification=True)
