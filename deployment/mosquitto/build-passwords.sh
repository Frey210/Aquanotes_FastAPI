#!/bin/sh
set -eu

IFS= read -r backend_password
IFS= read -r canary_password
backend_password=$(printf '%s' "$backend_password" | tr -d '\r')
canary_password=$(printf '%s' "$canary_password" | tr -d '\r')

mosquitto_passwd -b -c /tmp/aquanotes-passwords aquanotes-backend "$backend_password"
mosquitto_passwd -b /tmp/aquanotes-passwords AER2023AQ0029 "$canary_password"
chmod 600 /tmp/aquanotes-passwords
