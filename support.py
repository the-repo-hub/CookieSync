from selenium.common.exceptions import WebDriverException
from telebot.apihelper import ApiTelegramException
import time
from random import randint
import ctypes

def retry(fn):
    def inner(*args, **kwargs):
        err_counter = 0
        err_type = ''
        while err_counter <= 10:
            try:
                return fn(*args, **kwargs)

            # проблемы с интернетом
            except ConnectionError:
                err_counter += 1
                err_type = 'ConnectionError'

            # проблемы с интернетом для браузера
            except WebDriverException:
                err_counter += 1
                err_type = 'WebDriverException'

            # проблемы с телеграмом
            except ApiTelegramException:
                err_counter += 1
                err_type = 'ApiTelegramException'

            time.sleep(randint(1, 7))
        raise_error(f"Проблемы с интернетом.\nТип ошибки: {err_type}\nФункция: {fn.__name__}")

    return inner

def raise_error(error_txt):
    ctypes.windll.user32.MessageBoxW(0, error_txt, "Error message", 0)
    exit(1)