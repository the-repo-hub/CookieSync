# CookieSync

CookieSync — это инструмент для совместного и многократного использования одних и тех же cookies между разными браузерными сессиями. Он обеспечивает устойчивость, повторное использование и минимизирует повторные входы в систему используя общее разделенное хранилище.

### Разделенное хранилище

Представляет собой json файл, в котором ключ - это хэшированное название аккаунта, а значение - куки, закрепленные за этим аккаунтом.

### Возможности:
1. Обеспечивает автоматическое получение кук с сервера и отправку новых в совместное хранилище.
2. Поддерживает до 10 аккаунтов (разделенных хранилищ).
3. Не детектируется серверами.
4. Поддерживает практически неограниченное количество подключений к одному аккаунту.

Поддерживаемые браузеры: Firefox, Edge, Chrome

### Установка и запуск сервера

**Windows:** [пошаговая инструкция](cookieserver/WINDOWS.md) — установка Python,
настройка аккаунтов, firewall, TLS и автозапуск через Планировщик заданий.
Готовый шаблон: [server_config.windows.conf.example](cookieserver/server_config.windows.conf.example).

Зависимости сервера находятся в `cookieserver/requirements.txt`.
Команды выполняются из корня проекта с установленными зависимостями:

```bash
python -m pip install -r cookieserver/requirements.txt
python -m cookieserver.manage --help
python -m cookieserver.manage runserver
```

Сервер читает `cookieserver/server_config.conf`. По умолчанию включён TLS:
нужны PEM-сертификат и ключ. Для проверки в доверенной локальной сети
используйте `python -m cookieserver.manage runserver --no-tls` и URL `ws://`.

## License  
This project is proprietary. Unauthorized use is prohibited.
