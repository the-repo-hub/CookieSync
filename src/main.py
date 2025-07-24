"""Main file to run main functionality."""

import time
from configparser import ConfigParser, SectionProxy
from os import devnull
from typing import Any, Dict, List, Tuple, Type

from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver import Chrome, Edge, Firefox
from selenium.webdriver.chrome.options import ChromiumOptions as ChromeOptions
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.common.by import By
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.webdriver.edge.service import Service as EdgeService
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.webdriver.firefox.service import Service as FirefoxService
from selenium.webdriver.remote.webdriver import WebDriver

from src.choiches import CookieFields, ErrorMessages
from src.handlers import exception_run_handler, raise_error
from src.manager import MessageManager
from src.settings import INI_FILE_PATH

BaseDriverMeta: Type = type(WebDriver)


class BrowserDetector(object):
    """Detect browser class and his services and options."""

    browser_dictionary = {
        'Firefox': (Firefox, FirefoxService, FirefoxOptions),
        'Chrome': (Chrome, ChromeService, ChromeOptions),
        'Edge': (Edge, EdgeService, EdgeOptions),
    }

    def __init__(self, name: str, user_agent: str):
        """Create instance with options and service by name.

        Args:
            name: browser string capitalized name, like 'Firefox',
            user_agent: string User-Agent value.
        """
        self.name = name
        try:
            self.klass = self.browser_dictionary[name][0]
        except KeyError:
            raise_error(ErrorMessages.invalid_browser.value.format(browser=self.name))
        self.service = self.browser_dictionary[name][1](log_output=devnull)
        self.options = self.browser_dictionary[name][2]()
        if isinstance(self.options, FirefoxOptions):
            self.options.set_preference('general.useragent.override', user_agent)
        else:
            self.options.add_argument('--user-agent={user_agent}'.format(user_agent=user_agent))


class BrowserMeta(BaseDriverMeta):
    """Metaclass for detect browser in ini options and change ResoBrowser class inheritance."""

    def __new__(cls, name: str, bases: Tuple, attrs: Dict) -> Any:
        """Class creation method.

        Args:
            name: string class name.
            bases: tuple with inheritance order.
            attrs: dictionary with class variables and values.

        Returns:
            Edited class.
        """
        options = cls.get_ini_options()
        browser = BrowserDetector(
            name=options['browser'].capitalize(),
            user_agent=options['user-agent'].capitalize(),
        )  # type: ignore
        new_browser_class = super().__new__(cls, name, (browser.klass,), attrs)
        new_browser_class.hash = options.get('hash', 'None')
        new_browser_class.service = browser.service
        new_browser_class.options = browser.options
        return new_browser_class

    @classmethod
    def get_ini_options(cls) -> SectionProxy:
        """Get and check that ini options is correct.

        Returns:
            SectionProxy instance (like dict) with hash, user-agent and browser fields.
        """
        ini_options = ConfigParser()
        ini_content = ini_options.read(INI_FILE_PATH, encoding='UTF-8')
        # нет файла
        if not ini_content:
            raise_error(ErrorMessages.no_ini.value)
        try:
            options = ini_options['options']
        except KeyError:
            return raise_error(ErrorMessages.no_ini_options.value)
        for field, field_content in options.items():
            if field not in {'hash', 'browser', 'user-agent', 'proxy-server'}:
                raise_error(ErrorMessages.invalid_ini_field.value.format(field=field))
            if not options.get(field):
                raise_error(ErrorMessages.invalid_ini_value.value.format(value=field_content, field=field))
        return options


class ResoBrowser(Firefox, metaclass=BrowserMeta):
    """Main Webdriver class."""

    url_main = 'https://office.reso.ru/'
    manager = MessageManager()

    # will fill in meta:
    hash: str
    service: FirefoxService
    options: FirefoxOptions

    def __init__(self) -> None:
        """Initialize method for class."""
        super().__init__(service=self.service, options=self.options)
        self.need_to_set_telegram_cookies = False
        self.last_cookies = self.manager.get_telegram_cookies(self.hash)
        if isinstance(self.last_cookies, str):
            self.quit()
            raise_error(self.last_cookies)

    def delete_reso_cookies(self) -> None:
        """Delete only necessary reso cookies."""
        self.delete_cookie(CookieFields.aspnet.value)
        self.delete_cookie(CookieFields.reso_office60.value)

    def obtain_and_insert_cookies(self) -> None:
        """Get cookies from telegram and insert them in browser."""
        tele_cookies = self.manager.get_telegram_cookies(self.hash)
        if isinstance(tele_cookies, str):
            self.quit()
            raise_error(tele_cookies)
        self.delete_reso_cookies()
        for line in tele_cookies:
            self.add_cookie(line)
        self.last_cookies = tele_cookies

    def auth_complete(self) -> bool:
        """Check is authentication was complete.

        Returns:
            bool variable.
        """
        try:
            # welcome message
            self.find_element(By.XPATH, '/html/body/form/div[4]/div[1]/div[7]/div/div/div/div/div[1]')
        except NoSuchElementException:
            return True
        return False

    def get_browser_cookies(self) -> List:
        """Get cookies from browser.

        Returns:
            List with dict cookies.
        """
        cookies = [
            self.get_cookie(CookieFields.aspnet.value),
            self.get_cookie(CookieFields.reso_office60.value),
        ]
        # selenium bug, when point adds to domain
        if all(cookies):
            cookies[0].pop('domain')  # type: ignore
            cookies[1].pop('domain')  # type: ignore
            return cookies
        return raise_error(ErrorMessages.invalid_cookies.value)

    def logged_in(self) -> None:
        """Logic when browser is logged in service."""
        tele_cookies = self.manager.get_telegram_cookies(self.hash)
        if isinstance(tele_cookies, str):
            self.quit()
            raise_error(tele_cookies)
        browser_cookies = self.get_browser_cookies()

        if self.need_to_set_telegram_cookies:
            # somebody logged in
            self.manager.set_telegram_cookies(cookies=browser_cookies, hsh=self.hash)
            self.need_to_set_telegram_cookies = False

        elif self.last_cookies != browser_cookies:
            # i'm logged in, but cookies changed by server
            self.manager.set_telegram_cookies(cookies=browser_cookies, hsh=self.hash)
            self.last_cookies = browser_cookies

        elif browser_cookies != tele_cookies:
            # somebody changed cookies, but my cookies is normal
            self.obtain_and_insert_cookies()

    def logged_out(self) -> None:
        """Logic, when browser is logged out from service."""
        tele_cookies = self.manager.get_telegram_cookies(self.hash)
        if isinstance(tele_cookies, str):
            self.quit()
            raise_error(tele_cookies)
        if self.last_cookies == tele_cookies:
            self.need_to_set_telegram_cookies = True
        else:
            self.obtain_and_insert_cookies()
            self.get(self.url_main)

    @exception_run_handler
    def run(self) -> None:
        """Run main logic."""
        # if it will be removed, don't forget about implicitly wait
        self.get(self.url_main)
        self.obtain_and_insert_cookies()
        self.get(self.url_main)
        while True:
            if self.auth_complete():
                self.logged_in()
            else:
                self.logged_out()
            time.sleep(1)


if __name__ == '__main__':
    reso = ResoBrowser()
    reso.run()
