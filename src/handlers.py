"""Error handlers and decorators for program."""

import time
# for pyinstaller
from sys import exit
from typing import Any, Callable, Dict, Optional, Tuple

from selenium.common.exceptions import (
    InvalidCookieDomainException, InvalidSessionIdException, NoSuchWindowException, UnexpectedAlertPresentException,
    WebDriverException,
)
from selenium.webdriver.remote.webdriver import WebDriver
from telebot.apihelper import ApiTelegramException
from urllib3.exceptions import MaxRetryError

from src.exceptions import InvalidBotToken, InvalidHash, TelegramError
from requests import ConnectionError
import sys
import ctypes
import platform
from src.choiches import Systems
import subprocess

def retry(fn: Callable) -> Callable:
    """Retry decorator for handle errors.

    Args:
        fn: function that will be wrapped.

    Returns:
        Decorator closure.
    """

    def inner(*args: Tuple, **kwargs: Dict) -> Optional[Callable]:
        """Inner decorator function.

        Args:
            args: Tuple with any values.
            kwargs: Dictionary with any variables and values.
        """
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
            except InvalidHash:
                raise InvalidHash('Невалидный хэш')
            except InvalidBotToken:
                raise InvalidBotToken('Невалидный токен бота, бот не существует')
            # проблемы с телеграмм
            except ApiTelegramException:
                err_counter += 1
                err_type = 'ApiTelegramException'
            time.sleep(2)
        raise TelegramError(
            'Проблемы с интернетом.\nТип ошибки: {err_type}\nФункция: {name}'.format(
            err_type=err_type,
            name=fn.__name__,
            )
        )
    return inner


def exception_run_handler(fn: Callable) -> Callable:
    """Run function exception handler that.

    Args:
        fn: function that will be wrapped.
    """

    def inner(obj: WebDriver, *args: Tuple, **kwargs: Dict) -> Any:
        """Inner decorator function.

        Args:
            obj: ResoBrowser object.
            args: Tuple with any values.
            kwargs: Dictionary with any variables and values.
        """
        try:
            return fn(obj, *args, **kwargs)
        except NoSuchWindowException:
            # raises if first tab was closed
            try:
                obj.switch_to.window(obj.window_handles[0])
            except InvalidSessionIdException:
                obj.quit()
                exit(0)

        except UnexpectedAlertPresentException:
            # raises if browser had js alert
            pass

        except InvalidCookieDomainException:
            # raises if cookie adding attempt fails, for example, if self.get hasnt called
            pass

        except InvalidSessionIdException:
            exit(0)

        except IndexError:
            obj.quit()
            exit(0)

        except WebDriverException:
            obj.quit()
            exit(0)

        except MaxRetryError:
            exit(0)
    return inner

def show_error(title, message):
    system = platform.system()
    if system == Systems.windows:
        ctypes.windll.user32.MessageBoxW(0, message, title, 0x10)  # 0x10 — иконка ошибки
    else:
        subprocess.run(['zenity', '--error', '--title', title, '--text', message])

def exception_hook(exc_type, exc_value, exc_traceback):
    error_msg = f"Произошла ошибка:\n\n{str(exc_value)}"
    show_error("Ошибка Selenium", error_msg)

sys.excepthook = exception_hook
