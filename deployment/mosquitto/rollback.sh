#!/bin/sh
set -eu

systemctl disable --now mosquitto
rm -f /etc/mosquitto/conf.d/aquanotes.conf
systemctl enable --now emqx
systemctl is-active --quiet emqx
