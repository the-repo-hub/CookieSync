import configparser
import ctypes
import time
from subprocess import CREATE_NO_WINDOW
from sys import exit

import selenium.webdriver
from selenium.common.exceptions import NoSuchWindowException, WebDriverException, NoSuchElementException, \
    UnexpectedAlertPresentException, InvalidSessionIdException, InvalidCookieDomainException
from selenium.webdriver.chrome.options import ChromiumOptions as ChromeOptions
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.common.by import By
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.webdriver.edge.service import Service as EdgeService
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.webdriver.firefox.service import Service as FirefoxService

from ResoBot import AccountManager, raise_error


class GetValidBrowser:
    dct = {
        'Firefox': [selenium.webdriver.Firefox, FirefoxService, FirefoxOptions],
        'Chrome': [selenium.webdriver.Chrome, ChromeService, ChromeOptions],
        'Edge': [selenium.webdriver.Edge, EdgeService, EdgeOptions]
    }

    def __init__(self, ini_options):
        try:
            self.ini_browser = ini_options['options']['browser'].capitalize()
            self.class_ = self.dct[self.ini_browser][0]

            self.service = self.dct[self.ini_browser][1](log_path='NUL')
            self.service.creation_flags = CREATE_NO_WINDOW

            self.options = self.dct[self.ini_browser][2]()

            if self.ini_browser == 'Firefox':
                self.options.set_preference("general.useragent.override", ini_options['options']['user-agent'])
            else:
                self.options.add_argument(f"--user-agent='{ini_options['options']['user-agent']}'")
        except KeyError:
            raise_error("Не найден подходящий браузер")


def get_ini():
    try:
        ini_options = configparser.ConfigParser()
        result = ini_options.read('reso.ini', encoding='UTF-8')

        # нет файла
        if not result:
            raise_error("Не найден файл reso.ini")

        # проверка полей в options. Если нет options, то вызывается ошибка
        for line in ini_options['options']:
            if not (line == 'hash' or line == 'browser' or line == 'user-agent'):
                raise_error(f"Проблемы с ини-файлом, поле {line} не валидно")

        return ini_options

    except KeyError:
        raise_error("Проблемы с ини-файлом, не найдено поле options")


def get_reso_class():
    ini_options = get_ini()
    browser = GetValidBrowser(ini_options)

    class ResoBrowser(browser.class_):

        url_main = 'https://office.reso.ru/'
        manager = AccountManager()

        def __init__(self):
            super().__init__(service=browser.service, options=browser.options)
            self.need_to_overwrite_cookies = False
            self.hash = ini_options['options']['hash']

            self.last_cookies = self.manager[self.hash]
            if not self.last_cookies:
                self.quit()
                raise_error('Невалидный хэш')

        def delete_reso_cookies(self):
            self.delete_cookie('ASP.NET_SessionId')
            self.delete_cookie('ResoOffice60')

        def get_and_insert_cookies(self):

            tele_cookies = self.manager[self.hash]

            if not tele_cookies:
                self.quit()
                raise_error('Невалидный хэш')

            self.delete_reso_cookies()

            for line in tele_cookies:
                self.add_cookie(line)

            self.get(self.url_main)

            if not self.auth_complete():
                self.delete_reso_cookies()

            self.need_to_overwrite_cookies = False

        def find_element(self, *args, **kwargs):
            try:
                return super().find_element(*args, **kwargs)
            except NoSuchElementException:
                return None

        def auth_complete(self):
            if 'reso.ru' in self.current_url and self.url_main + 'login' not in self.current_url:
                welcome = self.find_element(By.XPATH,
                                            '/html/body/form/div[4]/div[1]/div[7]/div/div/div/div/div[1]')  # welcome msg
                qr = self.find_element(By.XPATH, '//*[@id="qrImage"]')  # qr
                if not welcome and not qr:
                    return True
            return False

        def get_cookies(self):
            result = [self.get_cookie('ASP.NET_SessionId'), self.get_cookie('ResoOffice60')]
            if None not in result:
                result[0].pop('domain')
                result[1].pop('domain')
                result[0]['sameSite'] = 'None'
                result[1]['sameSite'] = 'None'
            return result

        def run(self):
            self.get(self.url_main)  # костылек, без которого не вставляются куки
            first_opening = True

            while True:
                try:
                    if self.auth_complete():
                        first_opening = True
                        time.sleep(1)
                        tele_cookies = self.manager[self.hash]
                        get = self.get_cookies()

                        if self.need_to_overwrite_cookies and None not in get:
                            self.manager[self.hash] = self.get_cookies()
                            self.need_to_overwrite_cookies = False

                        if not tele_cookies:
                            self.quit()
                            raise_error('Невалидный хэш')

                        elif None in get:
                            continue

                        elif self.last_cookies != get:
                            self.manager[self.hash] = get
                            self.last_cookies = get

                        elif get != tele_cookies:
                            self.delete_reso_cookies()
                            for line in tele_cookies:
                                self.add_cookie(line)
                            self.last_cookies = self.get_cookies()

                    else:

                        if first_opening:
                            self.get_and_insert_cookies()
                            first_opening = False
                            continue

                        time.sleep(1)

                        self.need_to_overwrite_cookies = True

                        tele_cookies = self.manager[self.hash]
                        if not tele_cookies:
                            self.quit()
                            raise_error('Невалидный хэш')
                        elif self.last_cookies != tele_cookies:
                            self.get_and_insert_cookies()
                            self.last_cookies = tele_cookies

                except NoSuchWindowException:
                    for i in range(3):
                        try:
                            self.switch_to.window(self.window_handles[0])
                        except NoSuchWindowException:
                            pass
                        except WebDriverException:
                            break
                        except IndexError:
                            break
                    self.quit()
                    exit(0)

                except UnexpectedAlertPresentException:
                    pass

                except TypeError:
                    pass

                except InvalidCookieDomainException:
                    pass

                except InvalidSessionIdException:
                    self.quit()
                    exit(0)

                except IndexError:
                    self.quit()
                    exit(0)

                except WebDriverException:
                    self.quit()
                    exit(0)

    return ResoBrowser


if __name__ == '__main__':
    Reso = get_reso_class()
    with Reso() as r:
        r.run()


    # pyinstaller --onefile main.py --ico=reso-2-logo-png-transparent.ico --name=reso --windowed && venv-32\Scripts\pyinstaller.exe --onefile main.py --ico=reso-2-logo-png-transparent.ico --name=reso32 --windowed
