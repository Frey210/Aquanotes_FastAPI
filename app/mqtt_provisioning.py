import os
import re
import secrets
import subprocess


class MqttProvisioningError(RuntimeError):
    pass


def provision_device(uid: str) -> dict[str, str]:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{2,35}", uid):
        raise MqttProvisioningError("UID device tidak valid untuk MQTT")
    if os.getenv("MQTT_PROVISIONING_ENABLED", "false").lower() not in {"1", "true", "yes"}:
        raise MqttProvisioningError("Provisioning MQTT belum aktif")

    password = secrets.token_urlsafe(32)
    host = os.environ["MQTT_PROVISIONING_HOST"]
    user = os.getenv("MQTT_PROVISIONING_USER", "root")
    key = os.getenv("MQTT_PROVISIONING_KEY", "/run/secrets/mqtt-provisioner-key")
    known_hosts = os.getenv("MQTT_PROVISIONING_KNOWN_HOSTS", "/run/secrets/mqtt-known-hosts")
    port = os.getenv("MQTT_PROVISIONING_PORT", "22")
    command = [
        "ssh", "-T", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
        "-o", "StrictHostKeyChecking=yes", "-o", f"UserKnownHostsFile={known_hosts}",
        "-i", key, "-p", port, f"{user}@{host}", f"upsert {uid}",
    ]
    try:
        result = subprocess.run(command, input=password + "\n", text=True, capture_output=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise MqttProvisioningError("Broker MQTT tidak dapat dihubungi") from exc
    if result.returncode != 0:
        raise MqttProvisioningError("Credential MQTT gagal dibuat di broker")

    return {
        "mqtt_password": password,
        "secrets_h": f'#pragma once\n\n#define DEVICE_UID "{uid}"\n#define MQTT_PASSWORD "{password}"\n',
    }
