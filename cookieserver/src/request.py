"""Разбор обязательных полей клиентского запроса без изменения его UUID."""

from dataclasses import dataclass
from typing import Dict

from cookieserver.src.choices import Fields
from cookieserver.src.errors import HandleCommandError


@dataclass
class Request:
    """Запрос, создаваемый из полного JSON-объекта.

    После инициализации payload содержит вложенную нагрузку, а command,
    account, uuid и expected_revision доступны как отдельные атрибуты.
    Проверка cookies и ревизии остаётся в обработчиках команд и хранилище.
    """

    payload: Dict

    def __post_init__(self):
        """Извлекает поля и вызывает HandleCommandError при базовых ошибках запроса."""
        self.command = self.payload.get(Fields.command)
        self.account = self.payload.get(Fields.account)
        self.uuid = self.payload.get(Fields.uuid)
        self.expected_revision = self.payload.get(Fields.expected_revision)
        self.payload = self.payload.get(Fields.payload)

        if not self.command:
            raise HandleCommandError("No command specified")
        if not self.account:
            raise HandleCommandError("No account specified")
        if not isinstance(self.account, str) or not self.account.strip():
            raise HandleCommandError("Account name must be a non-empty string")
        if not self.uuid:
            raise HandleCommandError("No uuid specified")
