class ResoException(Exception):
    pass

class TelegramError(ResoException):
    pass

class IniFileError(ResoException):
    pass

class BrowserNotInstalled(ResoException):
    pass

class BrowserNotFoundError(IniFileError):
    pass

class NoIniFileError(IniFileError):
    msg = 'Не найден файл reso.ini'

class NoIniOptionsError(IniFileError):
    msg = 'Проблемы с ини-файлом, не найдено поле options'

class InvalidIniFieldError(IniFileError):
    msg = 'Проблемы с ини-файлом: поле {field} не валидно'

class InvalidIniValueError(IniFileError):
    msg = 'Проблемы с ини-файлом: значение {value} в поле {field} не валидно'

class InvalidBotToken(TelegramError):
    msg = 'Невалидный токен в .env файле'

class InvalidHash(TelegramError):
    msg = 'Невалидный хэш в reso.ini'
