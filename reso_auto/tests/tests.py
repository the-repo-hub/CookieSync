import json
import unittest
from threading import Thread
from time import sleep

from reso_auto.main import ResoBrowser
from reso_auto.manager import MessageManager


class ResoTestCase(unittest.TestCase):

    manager = MessageManager()
    testAccountName = 'testcase'

    @classmethod
    def setUpClass(cls) -> None:
        """Set up method that adds testCase account."""
        cls.manager.add_account(cls.testAccountName)

    def test_manager_start(self) -> None:
        """Test availability of pinned message."""
        chat = self.manager.bot.get_chat(self.manager.chat)
        self.assertTrue(chat.pinned_message)

    def test_accounts_managing(self) -> None:
        """Test add and remove account methods."""
        self.manager.remove_account(self.testAccountName)
        message = json.loads(self.manager.bot.get_chat(self.manager.chat).pinned_message.text)
        self.assertNotIn(self.testAccountName, message.keys())
        self.manager.add_account(self.testAccountName)
        message = json.loads(self.manager.bot.get_chat(self.manager.chat).pinned_message.text)
        self.assertIn(self.testAccountName, message.keys())

    def test_launch(self) -> None:
        """Test browser application launch."""
        ResoBrowser.hash = self.testAccountName
        r = ResoBrowser()
        Thread(target=r.run).start()
        sleep(5)
        r.quit()

    @classmethod
    def tearDownClass(cls) -> None:
        """Tear down method that removes testCase account."""
        cls.manager.remove_account(cls.testAccountName)


if __name__ == '__main__':
    unittest.main()
