"""Test module for ResoAuto."""

import unittest
from threading import Thread

from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as ec
from selenium.webdriver.support.ui import WebDriverWait

from client.manager import AdminManager
from src.main import ResoBrowser
from src.settings import SERVER_ADDRESS, SERVER_PORT
from cookieserver.src.server import Server

server = Server('localhost', SERVER_PORT)
server.start()
admin_manager = AdminManager(SERVER_ADDRESS, SERVER_PORT)
test_acc = 'test_acc1'
test_acc2 = 'test_acc2'

class ResoServerTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        admin_manager.add_account(test_acc)
        admin_manager.add_account(test_acc2)

    def test_server_started_correctly(self):
        self.assertEqual(len(server._accounts), 2)
        self.assertFalse(server._active_clients)

    def test_get_all(self):
        result = admin_manager.get_all_accounts()
        self.assertTrue(len(result) > 2)
        acc1, acc2 = result
        self.assertIn(acc1, server._accounts)
        self.assertIn(acc2, server._accounts)
        self.assertEqual(acc1, test_acc)
        self.assertEqual(acc2, test_acc2)
        self.assertFalse(server._active_clients)

    def test_get_cookies(self):
        result = admin_manager.get_cookies(test_acc)
        self.assertEqual(len(result), 2)
        self.assertFalse(server._active_clients)

    def test_add_remove_account(self):
        test_acc3 = 'test_acc3'
        admin_manager.add_account(test_acc3)
        self.assertIn(test_acc3, server._accounts)
        self.assertFalse(server._active_clients)
        result = admin_manager.get_cookies(test_acc3)
        self.assertTrue(result)
        admin_manager.remove_account(test_acc3)
        self.assertNotIn(test_acc3, server._accounts)
        self.assertFalse(server._active_clients)

    @classmethod
    def tearDownClass(cls):
        admin_manager.remove_account(test_acc)
        admin_manager.remove_account(test_acc2)

class ResoTestCase(unittest.TestCase):
    """Reso Testcase for bot and browser."""


    @classmethod
    def setUpClass(cls) -> None:
        """Set up method that adds testCase account."""
        admin_manager.add_account(test_acc)

    def test_manager_start(self) -> None:
        """Test availability of pinned message."""
        cookies = admin_manager.get_cookies(test_acc)
        self.assertEqual(len(cookies), 2)

    def test_accounts_managing(self) -> None:
        """Test add and remove account methods."""
        admin_manager.remove_account(test_acc)
        # cookies = self.manager.get_cookies(self.test_hash)
        # self.assertEqual(len(cookies), 2)
        admin_manager.add_account(test_acc)
        cookies = admin_manager.get_cookies(test_acc)
        self.assertEqual(len(cookies), 2)

    def test_launch(self) -> None:
        """Test browser application launch."""
        self.assertTrue(admin_manager.get_cookies(test_acc))
        with ResoBrowser() as browser:
            browser.hash = test_acc
            Thread(target=browser.start).start()
            WebDriverWait(browser, timeout=10).until(
                ec.presence_of_element_located(
                    (By.XPATH, '/html/body/form/div[4]/div[1]/div[7]/div/div/div/div/div[1]'),
                ),
            )
            browser.session_id = None

    @classmethod
    def tearDownClass(cls) -> None:
        """Tear down method that removes testCase account."""
        admin_manager.remove_account(test_acc)

if __name__ == '__main__':
    unittest.main()
