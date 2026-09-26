#!/bin/sh
set -eu

IFS= read -r backend_password
IFS= read -r canary_password
backend_password=$(printf '%s' "$backend_password" | tr -d '\r')
canary_password=$(printf '%s' "$canary_password" | tr -d '\r')
host=192.168.10.66
ca=/tmp/mqtt-ca.crt
plain_port=${MQTT_PLAIN_PORT:-1884}
tls_port=${MQTT_TLS_PORT:-8884}
payload='{"message_id":"broker-smoke-1","suhu":28.5}'
output="/tmp/mosquitto-smoke-$(id -u).out"

mosquitto_sub -h "$host" -p "$plain_port" -u aquanotes-backend -P "$backend_password" \
    -t 'devices/+/telemetry' -C 1 -W 5 >"$output" &
subscriber=$!
sleep 1
mosquitto_pub -h "$host" -p "$plain_port" -u AER2023AQ0029 -P "$canary_password" \
    -t devices/AER2023AQ0029/telemetry -q 1 -m "$payload"
wait "$subscriber"
grep -Fq 'broker-smoke-1' "$output"
echo 'plain MQTT auth/ACL: OK'

if mosquitto_pub -h "$host" -p "$plain_port" -t devices/AER2023AQ0029/telemetry \
    -m "$payload" >/dev/null 2>&1; then
    echo 'anonymous publish unexpectedly allowed' >&2
    exit 1
fi
echo 'anonymous rejection: OK'

mosquitto_pub -h "$host" -p "$tls_port" --cafile "$ca" \
    -u AER2023AQ0029 -P "$canary_password" \
    -t devices/AER2023AQ0029/telemetry -q 1 -m "$payload"
echo 'MQTTS certificate/auth: OK'

echo 'mosquitto smoke test: OK'
