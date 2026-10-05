#!/bin/sh
set -eu

IFS= read -r backend_password
IFS= read -r canary_password
backend_password=$(printf '%s' "$backend_password" | tr -d '\r')
canary_password=$(printf '%s' "$canary_password" | tr -d '\r')
base=/etc/mosquitto/aquanotes

install -d -o root -g mosquitto -m 750 "$base" "$base/certs"
install -o root -g mosquitto -m 640 /tmp/aquanotes.conf "$base/aquanotes.conf"
install -o mosquitto -g mosquitto -m 640 /tmp/acl "$base/acl"

cd "$base/certs"
if [ ! -f ca.key ]; then
    openssl genrsa -out ca.key 4096 >/dev/null 2>&1
    openssl req -x509 -new -sha256 -days 3650 -key ca.key \
        -subj "/CN=AquaNotes MQTT Internal CA" -out ca.crt >/dev/null 2>&1
fi
if [ ! -f server.key ]; then
    openssl genrsa -out server.key 2048 >/dev/null 2>&1
    openssl req -new -key server.key -subj "/CN=mqtt.farlabs.my.id" \
        -out server.csr >/dev/null 2>&1
    printf '%s\n' \
        'subjectAltName=DNS:mqtt.farlabs.my.id,IP:192.168.10.66' \
        'extendedKeyUsage=serverAuth' >server.ext
    openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key \
        -CAcreateserial -out server.crt -days 825 -sha256 \
        -extfile server.ext >/dev/null 2>&1
fi
chown root:mosquitto server.key server.crt ca.crt
chmod 640 server.key server.crt ca.crt

mosquitto_passwd -b -c "$base/passwords" aquanotes-backend "$backend_password"
mosquitto_passwd -b "$base/passwords" AER2023AQ0029 "$canary_password"
chown root:mosquitto "$base/passwords"
chmod 640 "$base/passwords"

sed -e 's/persistence true/persistence false/' \
    -e 's/listener 1883/listener 1884/' \
    -e 's/listener 8883/listener 8884/' \
    -e 's/listener 8083/listener 8085/' \
    "$base/aquanotes.conf" >"$base/stage.conf"
chown root:mosquitto "$base/stage.conf"
chmod 640 "$base/stage.conf"

openssl verify -CAfile ca.crt server.crt
