#!/bin/sh
set -eu

test -r /tmp/recovery.conf

systemctl stop mosquitto-stage.service 2>/dev/null || true
install -o root -g root -m 644 /etc/mosquitto/aquanotes/aquanotes.conf \
    /etc/mosquitto/conf.d/aquanotes.conf
systemctl disable --now emqx

install -d -m 755 /etc/systemd/system/mosquitto.service.d
install -o root -g root -m 644 /tmp/recovery.conf \
    /etc/systemd/system/mosquitto.service.d/recovery.conf
systemctl daemon-reload
systemctl reset-failed mosquitto

if systemctl enable --now mosquitto; then
    systemctl is-active --quiet mosquitto
    exit 0
fi

systemctl disable --now mosquitto 2>/dev/null || true
rm -f /etc/mosquitto/conf.d/aquanotes.conf
systemctl enable --now emqx
echo 'Mosquitto failed; EMQX rollback completed' >&2
exit 1
