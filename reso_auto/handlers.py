import time
from random import randint
from typing import Callable, Dict, List, Optional

from selenium.common.exceptions import (
    InvalidCookieDomainException, InvalidSessionIdException, NoSuchWindowException, UnexpectedAlertPresentException,
    WebDriverException,
)
from telebot.apihelper import ApiTelegramException
from urllib3.exceptions import MaxRetryError


def retry(fn: Callable) -> Callable:
    """Retry decorator for handle errors."""

    def inner(*args: List, **kwargs: Dict) -> Optional[Callable]:
        """Inner decorator function."""
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
        return None

    return inner


def exception_run_handler(fn: Callable):
    def inner(obj, *args, **kwargs):
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

        except TypeError:
            pass

        except InvalidCookieDomainException:
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


def raise_error(error_txt: str) -> None:
    """Raise window with error."""
    print(error_txt)
    exit(1)
