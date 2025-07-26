"""Main file to run main functionality."""

import time
from configparser import ConfigParser, SectionProxy
from os import devnull
from typing import Any, Dict, List, Tuple, Type

from selenium.common.exceptions import NoSuchElementException, NoSuchDriverException
from selenium.webdriver import Chrome, Edge, Firefox
from selenium.webdriver.chrome.options import ChromiumOptions as ChromeOptions
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.common.by import By
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.webdriver.edge.service import Service as EdgeService
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.webdriver.firefox.service import Service as FirefoxService
from selenium.webdriver.remote.webdriver import WebDriver

from src.choiches import CookieFields
from src.exceptions import NoIniFileError, NoIniOptionsError, InvalidIniFieldError, InvalidIniValueError, \
    BrowserNotFoundError, BrowserNotInstalled
from src.handlers import exception_run_handler
from src.manager import MessageManager
import os

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
        if self.name == 'Edge':
            # https://github.com/seleniumhq/selenium/issues/16073
            os.environ["SE_DRIVER_MIRROR_URL"] = "https://msedgedriver.microsoft.com"
        try:
            self.klass = self.browser_dictionary[name][0]
        except KeyError:
            raise BrowserNotFoundError(f'Браузер {self.name} не поддерживается программой. Проверьте корректность ввода данных в reso.ini файле.')
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
        new_browser_class.browser_name = options['browser'].capitalize()
        return new_browser_class

    @classmethod
    def get_ini_options(cls) -> SectionProxy:
        """Get and check that ini options is correct.

        Returns:
            SectionProxy instance (like dict) with hash, user-agent and browser fields.
        """
        ini_options = ConfigParser()
        #fixme: hardcode filenames
        ini_content = ini_options.read(filenames='reso.ini', encoding='UTF-8')
        # нет файла
        if not ini_content:
            raise NoIniFileError(NoIniFileError.msg)
        try:
            options = ini_options['options']
        except KeyError:
            raise NoIniOptionsError(NoIniFileError.msg)
        for field, field_content in options.items():
            if field not in {'hash', 'browser', 'user-agent', 'proxy-server'}:
                raise InvalidIniFieldError(InvalidIniFieldError.msg.format(field=field))
            if not options.get(field):
                raise InvalidIniValueError(InvalidIniValueError.msg.format(field=field, value=field_content))
        return options


class ResoBrowser(Firefox, metaclass=BrowserMeta):
    """Main Webdriver class."""

    url_main = 'https://office.reso.ru/'
    manager = MessageManager()

    # will fill in meta:
    hash: str
    service: FirefoxService
    options: FirefoxOptions
    browser_name: str

    def __init__(self) -> None:
        """Initialize method for class."""
        #browser in ini file is correct, but not installed in system
        try:
            super().__init__(service=self.service, options=self.options)
        except NoSuchDriverException:
            raise BrowserNotInstalled(f'Браузер {self.browser_name} не установлен в системе')
        self.need_to_set_telegram_cookies = False
        self.last_cookies = self.manager.get_telegram_cookies(self.hash)

    def delete_reso_cookies(self) -> None:
        """Delete only necessary reso cookies."""
        self.delete_cookie(CookieFields.aspnet)
        self.delete_cookie(CookieFields.reso_office60)

    def obtain_and_insert_cookies(self) -> None:
        """Get cookies from telegram and insert them in browser."""
        tele_cookies = self.manager.get_telegram_cookies(self.hash)
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
            self.get_cookie(CookieFields.aspnet),
            self.get_cookie(CookieFields.reso_office60),
        ]
        return cookies

    def logged_in(self) -> None:
        """Logic when browser is logged in service."""
        tele_cookies = self.manager.get_telegram_cookies(self.hash)
        browser_cookies = self.get_browser_cookies()

        if self.need_to_set_telegram_cookies:
            # зашел текущий клиент, у него теперь другие куки и нужно поменять в телеге
            self.manager.set_telegram_cookies(cookies=browser_cookies, hsh=self.hash)
            self.need_to_set_telegram_cookies = False
            self.last_cookies = browser_cookies
        elif self.last_cookies != browser_cookies:
            # я залогинен, но ресо сервер изменил мне куки
            self.manager.set_telegram_cookies(cookies=browser_cookies, hsh=self.hash)
            self.last_cookies = browser_cookies
        elif browser_cookies != tele_cookies:
            # другой клиент изменил кукисы на свои, рабочие, но при этом я тоже залогинен, так что нужно унифицировать
            self.obtain_and_insert_cookies()

    def logged_out(self) -> None:
        """Logic, when browser is logged out from service."""
        tele_cookies = self.manager.get_telegram_cookies(self.hash)
        if self.last_cookies == tele_cookies:
            # в телеге лежат неверные куки, которые я пытался использовать
            self.need_to_set_telegram_cookies = True
        else:
            # кто-то изменил куки и они рабочие с высокой вероятностью
            self.need_to_set_telegram_cookies = False
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
    with ResoBrowser() as driver:
        driver.run()
