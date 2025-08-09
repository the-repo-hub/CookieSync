#!/bin/bash
set -e
SERVICE_NAME="resoserver"
SERVICE_FILE="/usr/lib/systemd/user/${SERVICE_NAME}.service"
cp ${SERVICE_NAME}.service $SERVICE_FILE
chmod 644 $SERVICE_FILE
systemctl --user daemon-reload
systemctl --user enable $SERVICE_NAME
systemctl --user start $SERVICE_NAME
systemctl --user status $SERVICE_NAME --no-pager
