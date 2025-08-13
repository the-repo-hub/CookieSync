"""Test module for ResoAuto."""
import os
import unittest
from threading import Thread

from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as ec
from selenium.webdriver.support.ui import WebDriverWait

from client.manager import Manager
from src.main import ResoBrowser
from src.settings import SERVER_ADDRESS, SERVER_PORT, INI_PATH



class ResoTestCase(unittest.TestCase):
    """Reso Testcase for bot and browser."""

    manager = Manager(SERVER_ADDRESS, SERVER_PORT)
    test_hash = 'testcase'

    @classmethod
    def setUpClass(cls) -> None:
        """Set up method that adds testCase account."""
        cls.manager.add_account(cls.test_hash)

    def test_manager_start(self) -> None:
        """Test availability of pinned message."""
        cookies = self.manager.get_cookies(self.test_hash)
        self.assertEqual(len(cookies), 2)

    def test_accounts_managing(self) -> None:
        """Test add and remove account methods."""
        self.manager.remove_account(self.test_hash)
        # cookies = self.manager.get_cookies(self.test_hash)
        # self.assertEqual(len(cookies), 2)
        self.manager.add_account(self.test_hash)
        cookies = self.manager.get_cookies(self.test_hash)
        self.assertEqual(len(cookies), 2)

    def test_launch(self) -> None:
        """Test browser application launch."""
        self.assertTrue(self.manager.get_cookies(self.test_hash))
        with ResoBrowser(self.test_hash) as browser:
            browser.hash = self.test_hash
            thread = Thread(target=browser.start)
            thread.start()
            WebDriverWait(browser, timeout=10).until(
                ec.presence_of_element_located(
                    (By.XPATH, '/html/body/form/div[4]/div[1]/div[7]/div/div/div/div/div[1]'),
                ),
            )
            # эмулируем закрытие браузера пользователем (нужно, чтобы остановился вечный цикл)
            browser.session_id = None

    @classmethod
    def tearDownClass(cls) -> None:
        """Tear down method that removes testCase account."""
        cls.manager.remove_account(cls.test_hash)
        cls.manager.close()

if __name__ == '__main__':
    unittest.main()
