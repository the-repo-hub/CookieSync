"""Имена команд и полей JSON-протокола CookieSync."""


class Commands:
    """Поддерживаемые клиентские команды; set также используется для push."""

    set = 'set'
    register = 'register'
    refresh = 'refresh'


class Fields:
    """Единые ключи протокола, включая uuid для корреляции запросов и ответов."""

    command = 'command'
    account = 'account'
    result = 'result'
    message = 'message'
    payload = 'payload'
    uuid = 'uuid'
    accepted = 'accepted'
    revision = 'revision'
    retry_after = 'retry_after'
    expected_revision = 'expected_revision'
