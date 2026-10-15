#!/bin/bash
set -euo pipefail

usage() {
    printf 'Usage: sudo bash cookieserver/install.sh [--tls|--no-tls]\n'
    printf 'Project location: /opt/CookieSync (prepare .venv and server_config.conf first).\n'
    printf 'Without an option, the unit defaults to TLS and existing drop-ins are preserved.\n'
}

if [[ $# -gt 1 ]]; then usage >&2; exit 2; fi
TRANSPORT="${1:-}"
case "$TRANSPORT" in
    --help|-h) usage; exit 0 ;;
    ""|--tls|--no-tls) ;;
    *) usage >&2; exit 2 ;;
esac

if [[ $EUID -ne 0 ]]; then
    printf 'Run this installer as root (sudo).\n' >&2
    exit 1
fi

PROJECT=/opt/CookieSync
SCRIPT_DIR="$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")"
SERVICE_NAME=cookiesync.service
SERVICE_FILE="/etc/systemd/system/$SERVICE_NAME"
PYTHON="$PROJECT/.venv/bin/python"
if [[ ! -x "$PYTHON" || ! -f "$PROJECT/cookieserver/manage.py" ]]; then
    printf 'Copy the project to %s, create .venv and install cookieserver/requirements.txt first.\n' "$PROJECT" >&2
    exit 1
fi

if ! id -u cookiesync >/dev/null 2>&1; then
    useradd --system --user-group --home-dir "$PROJECT" --no-create-home --shell /usr/sbin/nologin cookiesync
fi
install -d -o cookiesync -g cookiesync -m 700 "$PROJECT/cookieserver/accounts"
chown -R cookiesync:cookiesync "$PROJECT/cookieserver/accounts"
install --backup=numbered -m 644 "$SCRIPT_DIR/resoserver.service" "$SERVICE_FILE"

if [[ -n "$TRANSPORT" ]]; then
    OVERRIDE_DIR="/etc/systemd/system/$SERVICE_NAME.d"
    install -d -m 755 "$OVERRIDE_DIR"
    EXTRA_ARGS=""
    if [[ "$TRANSPORT" == --no-tls ]]; then EXTRA_ARGS=" --no-tls"; fi
    printf '[Service]\nExecStart=\nExecStart=%s -m cookieserver.manage runserver%s\n' \
        "$PYTHON" "$EXTRA_ARGS" > "$OVERRIDE_DIR/cookiesync-transport.conf"
fi

systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
systemctl restart "$SERVICE_NAME"
systemctl status "$SERVICE_NAME" --no-pager
