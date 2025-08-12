"""Main file to run main functionality."""
import os
import threading
import time
from configparser import ConfigParser, SectionProxy
from os import devnull
from typing import Any, Dict, List, Tuple, Type, Optional

from selenium.common.exceptions import InvalidSessionIdException
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

from client.manager import Manager
from src.choiches import CookieFields
from src.exceptions import NoIniFileError, NoIniOptionsError, InvalidIniFieldError, InvalidIniValueError, \
    BrowserNotFoundError, BrowserNotInstalled
from src.handlers import selenium_exception_handler
from src.settings import INI_PATH, SERVER_PORT, SERVER_ADDRESS

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
        self.service: FirefoxService | ChromeService | EdgeService = self.browser_dictionary[name][1](log_output=devnull)
        self.options: FirefoxOptions | ChromeOptions | EdgeOptions = self.browser_dictionary[name][2]()
        if isinstance(self.options, FirefoxOptions):
            self.options.set_preference('general.useragent.override', user_agent)
            self.options.set_preference("dom.webdriver.enabled", False)
            self.options.set_preference("useAutomationExtension", False)  # на всякий случай
            self.options.set_preference("devtools.jsonview.enabled", False)
        else:
            self.options.add_argument('--user-agent={user_agent}'.format(user_agent=user_agent))
            self.options.add_experimental_option("excludeSwitches", ["enable-automation"])
            self.options.add_argument("--disable-blink-features=AutomationControlled")
            self.options.set_capability("unhandledPromptBehavior", "ignore")


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
        ini_content = ini_options.read(filenames=INI_PATH, encoding='UTF-8')
        # нет файла
        if not ini_content:
            raise NoIniFileError(NoIniFileError.msg)
        try:
            options = ini_options['options']
        except KeyError:
            raise NoIniOptionsError(NoIniFileError.msg)
        for field, field_content in options.items():
            if field not in {'hash', 'browser', 'user-agent'}:
                raise InvalidIniFieldError(InvalidIniFieldError.msg.format(field=field))
            if not options.get(field):
                raise InvalidIniValueError(InvalidIniValueError.msg.format(field=field, value=field_content))
        return options


class ResoBrowser(Firefox, metaclass=BrowserMeta):
    """Main Webdriver class."""

    url_main = 'https://office.reso.ru/'
    manager = Manager(SERVER_ADDRESS, SERVER_PORT)

    # will fill in meta:
    hash: str
    service: FirefoxService
    options: FirefoxOptions
    browser_name: str #capitalized

    def __init__(self) -> None:
        """Initialize method for class."""
        #browser in ini file is correct, but not installed in system
        try:
            super().__init__(service=self.service, options=self.options)
        except NoSuchDriverException:
            raise BrowserNotInstalled(f'Браузер {self.browser_name} не установлен в системе')
        self.need_to_set_telegram_cookies = False
        self.last_cookies = None

    def delete_reso_cookies(self) -> None:
        """Delete only necessary reso cookies."""
        self.delete_cookie(CookieFields.aspnet)
        self.delete_cookie(CookieFields.reso_office60)

    def insert_cookies(self, tele_cookies: List) -> None:
        """Get cookies from telegram and insert them in browser."""
        self.delete_reso_cookies()
        for line in tele_cookies:
            self.add_cookie(line)

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

    def get_browser_cookies(self) -> Optional[List]:
        """Get cookies from browser.

        Returns:
            List with dict cookies.
        """
        cookies = [
            self.get_cookie(CookieFields.aspnet),
            self.get_cookie(CookieFields.reso_office60),
        ]
        #иногда сетится null, чтобы избежать этого:
        if all(cookies):
            return cookies
        return None

    def logged_in(self) -> None:
        """Logic when browser is logged in service."""
        browser_cookies = self.get_browser_cookies()
        if browser_cookies and self.need_to_set_telegram_cookies:
            # зашел текущий клиент, у него теперь другие куки и нужно поменять в телеге
            self.manager.set_cookies(cookies=browser_cookies, hsh=self.hash)
            self.need_to_set_telegram_cookies = False
            self.last_cookies = browser_cookies
        elif browser_cookies and self.last_cookies != browser_cookies:
            # я залогинен, но ресо сервер изменил мне куки
            self.manager.set_cookies(cookies=browser_cookies, hsh=self.hash)
            self.last_cookies = browser_cookies

    def update_cookies(self) -> None:
        cookies = self.manager.queue.get()
        self.insert_cookies(cookies)
        self.last_cookies = cookies
        self.manager.socket_event.clear()
        self.need_to_set_telegram_cookies = False
        self.get(self.url_main)

    def _run(self) -> None:
        """Run main logic."""
        while self.session_id:
            if self.manager.socket_event.is_set():
                # единственное условие срабатывания - сервер прислал рабочие куки
                self.update_cookies()
            elif self.auth_complete():
                self.logged_in()
            else:
                # если нас выкинет во время работы, то нужно использовать эту переменную снова
                self.need_to_set_telegram_cookies = True
            time.sleep(1)

    @selenium_exception_handler
    def start(self):
        self.last_cookies = self.manager.register(self.hash)
        self.get(self.url_main)
        self.insert_cookies(self.last_cookies)
        threading.Thread(target=self.manager.start_cookies_receiver).start()
        self.get(self.url_main)
        self._run()

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            self.manager.shutdown()
        except OSError:
            pass
        self.quit()
        if exc_type:
            if issubclass(exc_type, InvalidSessionIdException):
                return True
            if issubclass(exc_type, IndexError):
                # driver.switch_to.window fails during closing
                return True
            raise exc_type(exc_val)
        return False


if __name__ == '__main__':
    with ResoBrowser() as driver:
        driver.start()
