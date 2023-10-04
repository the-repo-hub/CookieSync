from enum import Enum


class CookieFields(str, Enum):
    """Types for cookie names."""

    ASPNET = 'ASP.NET_SessionId'
    ResoOffice60 = 'ResoOffice60'


class ErrorMessages(str, Enum):
    """Types for error messages."""

    invalid_hash = 'Невалидный хэш'
    invalid_browser = 'Недоступный браузер {browser}'
    no_ini = 'Не найден файл reso.ini'
    no_ini_options = 'Проблемы с ини-файлом, не найдено поле options'
    invalid_ini_field = 'Проблемы с ини-файлом: поле {field} не валидно'
    invalid_ini_value = 'Проблемы с ини-файлом: значение {value} в поле {field} не валидно'

