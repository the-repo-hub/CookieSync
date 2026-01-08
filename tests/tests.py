"""Test module for ResoAuto."""

from threading import Thread

from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as ec
from selenium.webdriver.support.ui import WebDriverWait

from client.manager import AdminManager, Manager
from src.main import ResoBrowser
from src.settings import SERVER_ADDRESS, SERVER_PORT
from cookieserver.src.server import Server
import pytest
from cookieserver.src.client import Client
import time

test_acc = 'test_acc1'
test_acc2 = 'test_acc2'
test_acc3 = 'test_acc3'

@pytest.fixture(scope="session", autouse=True)
def class_setup_and_teardown():
    # Перед запуском тестов в классе
    server = Server('localhost', SERVER_PORT)
    t = Thread(target=server.start)
    t.start()
    admin_manager = AdminManager('localhost', SERVER_PORT)
    admin_manager.add_file(test_acc)
    admin_manager.add_file(test_acc2)

    yield admin_manager, server

    admin_manager.remove_file(test_acc)
    admin_manager.remove_file(test_acc2)
    # в случае провала останется, поэтому
    admin_manager.remove_file(test_acc3)

    server.stop()
    t.join()

class TestCookieServer:

    @staticmethod
    def test_get_all(class_setup_and_teardown):
        admin_manager, server = class_setup_and_teardown
        result = admin_manager.get_all_accounts()
        acc1, acc2 = result[-2:]
        assert acc1 != acc2
        assert acc1 in server._storage._accounts
        assert acc2 in server._storage._accounts
        assert acc1 in (test_acc, test_acc2)
        assert acc2 in (test_acc, test_acc2)
        assert not Client.registered_clients

    @staticmethod
    def test_get_cookies(class_setup_and_teardown):
        admin_manager, server = class_setup_and_teardown
        cookies = admin_manager.get_cookies(test_acc)
        assert len(cookies) == 2
        assert not Client.registered_clients

    @staticmethod
    def test_add_remove_account(class_setup_and_teardown):
        admin_manager, server = class_setup_and_teardown
        admin_manager.add_file(test_acc3)
        assert test_acc3 in server._storage._accounts
        assert not Client.registered_clients
        cookies = admin_manager.get_cookies(test_acc3)
        assert len(cookies) == 2
        admin_manager.remove_file(test_acc3)
        assert test_acc3 not in server._storage._accounts
        assert not Client.registered_clients

    @staticmethod
    def test_register_client(class_setup_and_teardown):
        admin_manager, server = class_setup_and_teardown
        cookies = admin_manager.register(test_acc)
        assert len(cookies) == 2
        assert Client.registered_clients[test_acc]
        # нужно убрать зареганого клиента, единственный способ - удалить акк и создать снова
        admin_manager.remove_file(test_acc)
        admin_manager.add_file(test_acc)
        assert not Client.registered_clients.get(test_acc)

    @staticmethod
    def test_set_cookies(class_setup_and_teardown):
        admin_manager, server = class_setup_and_teardown
        # эмуляция запуска двух приложений с одним хранилищем
        user_manager1 = Manager('localhost', SERVER_PORT)
        user_manager2 = Manager('localhost', SERVER_PORT)
        # все соединения регистрируются для получения кук при запуске
        original_cookies = user_manager1.register(test_acc)
        # мы ничего не меняли, куки создаются из одного файла и должны быть одинаковыми
        assert original_cookies == user_manager2.register(test_acc)
        # запускаем ресиверы, чтобы ждать
        Thread(target=user_manager1.start_cookies_receiver).start()
        Thread(target=user_manager2.start_cookies_receiver).start()
        cookie_to_set = [{1:1}, {1:1}]
        user_manager1.set_cookies(test_acc, cookie_to_set)
        # time.sleep(3)
        # засетили новую куку, проверяем на сервере и через запрос
        assert server._storage._accounts[test_acc] == cookie_to_set
        assert admin_manager.get_cookies(test_acc) == cookie_to_set
        # не должно получиться, поскольку не прошло время
        user_manager2.set_cookies(test_acc, original_cookies)
        assert server._storage._accounts[test_acc] == cookie_to_set
        assert admin_manager.get_cookies(test_acc) == cookie_to_set
        # сбросим таймер и попробуем еще разок
        server._storage._cookie_timer[test_acc] = time.time() - 60
        user_manager2.set_cookies(test_acc, original_cookies)
        assert server._storage._accounts[test_acc] == original_cookies


class TestResoMain:

    @staticmethod
    def test_launch() -> None:
        """Test browser application launch."""
        with ResoBrowser() as browser:
            browser.hash = test_acc
            Thread(target=browser.start).start()
            WebDriverWait(browser, timeout=10).until(
                ec.presence_of_element_located(
                    (By.XPATH, '/html/body/form/div[4]/div[1]/div[7]/div/div/div/div/div[1]'),
                ),
            )
            # эмулируем закрытие
            browser.session_id = None
