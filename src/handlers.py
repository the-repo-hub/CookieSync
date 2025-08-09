"""Error handlers and decorators for program."""

import ctypes
import platform
import subprocess
import sys
import time
from http.client import RemoteDisconnected
# for pyinstaller
from sys import exit
from typing import Any, Callable, Dict, Tuple

from selenium.common.exceptions import (
    InvalidCookieDomainException, InvalidSessionIdException, NoSuchWindowException, UnexpectedAlertPresentException,
    WebDriverException
)
from selenium.webdriver.remote.webdriver import WebDriver
from urllib3.exceptions import MaxRetryError

from src.choiches import Systems


def exception_run_handler(fn: Callable) -> Callable:
    """Run function exception handler that.

    Args:
        fn: function that will be wrapped.
    """

    def inner(driver: WebDriver, *args: Tuple, **kwargs: Dict) -> Any:
        """Inner decorator function.

        Args:
            driver: ResoBrowser object.
            args: Tuple with any values.
            kwargs: Dictionary with any variables and values.
        """
        while True:
            try:
                return fn(driver, *args, **kwargs)
            except NoSuchWindowException:
                # raises if first tab was closed
                try:
                    driver.switch_to.window(driver.window_handles[0])
                except InvalidSessionIdException:
                    driver.quit()
                    exit(0)
            except UnexpectedAlertPresentException:
                # raises if browser had js alert
                pass
            except InvalidCookieDomainException:
                # raises if cookie adding attempt fails, for example, if self.get hasn't called
                pass
            except InvalidSessionIdException:
                exit(0)
            except IndexError:
                driver.quit()
                break
            except WebDriverException:
                driver.quit()
                break
            except MaxRetryError:
                break
            # если закрыть браузер при выполнении второго гет запроса
            except RemoteDisconnected:
                break
            time.sleep(1)
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
    exit(1)

sys.excepthook = exception_hook
