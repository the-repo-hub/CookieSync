"""Error handlers and decorators for program."""

import time
from typing import Any, Callable, Dict, Tuple

from selenium.common.exceptions import (
    InvalidCookieDomainException, NoSuchWindowException, UnexpectedAlertPresentException
)
from selenium.webdriver.remote.webdriver import WebDriver


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
                driver.switch_to.window(driver.window_handles[0])
            except UnexpectedAlertPresentException:
                # raises if browser had js alert
                pass
            except InvalidCookieDomainException:
                # raises if cookie adding attempt fails, for example, if self.get hasn't called
                pass
            time.sleep(1)
    return inner