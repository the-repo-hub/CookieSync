# CookieSync на Linux (systemd)

Ниже используется каталог `/opt/CookieSync`, Python 3.11+ и системный сервис
`cookiesync.service`. Скопируйте проект в этот каталог перед установкой.

## Подготовка

На Ubuntu/Debian установите Python и поддержку venv:

```bash
sudo apt update
sudo apt install python3 python3-venv
cd /opt/CookieSync
sudo python3 -m venv .venv
sudo .venv/bin/python -m pip install -r cookieserver/requirements.txt
```

Настройки сервера находятся в `cookieserver/server_config.conf`. Аккаунты
создаются автоматически при регистрации расширений и сохраняются в
`cookieserver/accounts`. Работать с одним каталогом аккаунтов должен один
экземпляр сервера.

## Сервис для локальной сети без TLS

Из корня проекта:

```bash
sudo bash cookieserver/install.sh --no-tls
```

Установщик создаёт пользователя `cookiesync`, выдаёт ему каталог аккаунтов,
копирует шаблон `cookieserver/resoserver.service` в
`/etc/systemd/system/cookiesync.service` и настраивает запуск через `.venv`.
Существующий основной unit сохраняется в нумерованной резервной копии.
Параметр `--no-tls` задаётся отдельным drop-in-файлом
`/etc/systemd/system/cookiesync.service.d/cookiesync-transport.conf`.

В расширении используйте `ws://mnas:52314` или адрес вашего сервера.
Проверьте доступность TCP-порта `52314` в firewall, маршрутизацию и DNS-имя `mnas`.

Если уже используется сервис с другим именем, обновите его настройки вместо
запуска второго экземпляра на том же порту.

## Сервис с TLS

Подготовьте PEM-сертификат и ключ, которым доверяют клиентские браузеры.
В секции `[server]` укажите абсолютные пути:

```ini
cert = /opt/CookieSync/cookieserver/keys/fullchain.pem
key = /opt/CookieSync/cookieserver/keys/privkey.pem
```

Убедитесь, что пользователь `cookiesync` может читать эти файлы и проходить
через их родительские каталоги. Если пользователя ещё нет, создайте его перед
настройкой прав доступа:

```bash
sudo useradd --system --user-group --home-dir /opt/CookieSync --no-create-home --shell /usr/sbin/nologin cookiesync
```

После подготовки сертификатов:

```bash
sudo bash cookieserver/install.sh --tls
```

Адрес в расширении — `wss://имя-из-сертификата:52314`.
Вызов установщика без аргументов использует TLS по умолчанию, но сохраняет
ранее созданные drop-in-настройки. Для явного переключения используйте `--tls`
или `--no-tls`. Другие пользовательские drop-in-файлы также учитываются systemd.

## Управление и обновление

```bash
sudo systemctl status cookiesync.service --no-pager
sudo journalctl -u cookiesync.service -f
sudo systemctl restart cookiesync.service
sudo systemctl stop cookiesync.service
```

После изменения кода или конфига достаточно перезапуска сервиса. После изменения
unit/drop-in сначала выполните `sudo systemctl daemon-reload`.
После продления TLS-сертификата также нужен перезапуск сервера.

Обновляйте код при остановленном сервисе, сохраняя каталог аккаунтов, конфиг
и ключи. Для версий с новой командой протокола (например, `refresh` в 1.2.0)
сначала обновляется сервер, затем расширения.

## Ручной запуск и тесты

```bash
make run_server ARGS=--no-tls
# TLS по умолчанию:
make run_server
```

Не запускайте ручной экземпляр одновременно с сервисом на том же порту.
Для разработки установите `requirements-dev.txt` и выполните `make test`
из корня проекта. Эта команда запускает pytest и Node-тесты.
