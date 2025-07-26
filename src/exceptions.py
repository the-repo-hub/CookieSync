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
    msg = 'Проблемы с reso.ini, не найдено поле options'

class InvalidIniFieldError(IniFileError):
    msg = 'Проблемы с reso.ini: поле "{field}" не валидно'

class InvalidIniValueError(IniFileError):
    msg = 'Проблемы с reso.ini: значение "{value}" в поле "{field}" не валидно'

class InvalidBotToken(TelegramError):
    msg = 'Невалидный токен в .env файле'

class InvalidHash(TelegramError):
    msg = 'Невалидный хэш "{hash}" в reso.ini, такой хэш отсутствует на сервере.'
