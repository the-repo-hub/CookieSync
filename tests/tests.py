"""Test module for ResoAuto."""

import json
import unittest
from threading import Thread

from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from src.main import ResoBrowser
from src.manager import MessageManager


class ResoTestCase(unittest.TestCase):
    """Reso Testcase for bot and browser."""

    manager = MessageManager()
    test_account_name = 'testcase'

    @classmethod
    def setUpClass(cls) -> None:
        """Set up method that adds testCase account."""
        cls.manager.add_account(cls.test_account_name)

    def test_manager_start(self) -> None:
        """Test availability of pinned message."""
        chat = self.manager.bot.get_chat(self.manager.chat)
        self.assertTrue(chat.pinned_message)

    def test_accounts_managing(self) -> None:
        """Test add and remove account methods."""
        self.manager.remove_account(self.test_account_name)
        message = json.loads(self.manager.bot.get_chat(self.manager.chat).pinned_message.text)
        self.assertNotIn(self.test_account_name, message.keys())
        self.manager.add_account(self.test_account_name)
        message = json.loads(self.manager.bot.get_chat(self.manager.chat).pinned_message.text)
        self.assertIn(self.test_account_name, message.keys())

    def test_launch(self) -> None:
        """Test browser application launch."""
        ResoBrowser.hash = self.test_account_name
        browser = ResoBrowser()
        thread = Thread(target=browser.run)
        thread.start()
        WebDriverWait(browser, timeout=10).until(
            EC.presence_of_element_located(
                (By.XPATH, '/html/body/form/div[4]/div[1]/div[7]/div/div/div/div/div[1]'),
            ),
        )
        self.assertTrue(thread.is_alive())
        browser.quit()

    @classmethod
    def tearDownClass(cls) -> None:
        """Tear down method that removes testCase account."""
        cls.manager.remove_account(cls.test_account_name)


if __name__ == '__main__':
    unittest.main()
