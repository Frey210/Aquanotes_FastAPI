import json
import logging
import os
import threading

import paho.mqtt.client as mqtt

from app import schemas
from app.database import SessionLocal
from app.sensor_ingestion import ingest_sensor_data

logger = logging.getLogger(__name__)
_client: mqtt.Client | None = None
_reconnect_timer: threading.Timer | None = None


def parse_mqtt_payload(topic: str, payload: bytes):
    parts = topic.split("/")
    if len(parts) != 3 or parts[0] != "devices" or parts[2] != "telemetry":
        raise ValueError("Invalid telemetry topic")
    uid = parts[1]
    body = json.loads(payload)
    if not isinstance(body, dict):
        raise ValueError("Telemetry payload must be a JSON object")
    message_id = body.pop("message_id", None)
    if not isinstance(message_id, str) or not 1 <= len(message_id) <= 128:
        raise ValueError("message_id is required and must be 1-128 characters")
    if body.get("uid") not in {None, uid}:
        raise ValueError("Payload UID does not match topic UID")
    body["uid"] = uid
    return schemas.SensorDataCreate.model_validate(body), message_id


def parse_ota_status_payload(topic: str, payload: bytes):
    parts = topic.split("/")
    if len(parts) != 4 or parts[0] != "devices" or parts[2:] != ["ota", "status"]:
        raise ValueError("Invalid OTA status topic")
    uid = parts[1]
    body = json.loads(payload)
    if not isinstance(body, dict):
        raise ValueError("OTA status payload must be a JSON object")
    return uid, schemas.OtaStatusMessage.model_validate(body)


def start_mqtt_consumer() -> bool:
    global _client
    if os.getenv("MQTT_ENABLED", "false").lower() not in {"1", "true", "yes"}:
        return False

    username = os.getenv("MQTT_USERNAME")
    password = os.getenv("MQTT_PASSWORD")
    if not username or not password:
        raise RuntimeError("MQTT_USERNAME and MQTT_PASSWORD are required")

    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id=os.getenv("MQTT_CLIENT_ID", "aquanotes-backend"),
        clean_session=False,
        protocol=mqtt.MQTTv311,
        manual_ack=True,
    )
    client.username_pw_set(username, password)
    ca_file = os.getenv("MQTT_TLS_CA")
    if ca_file:
        client.tls_set(ca_certs=ca_file)
    client.on_connect = _on_connect
    client.on_message = _on_message
    client.on_disconnect = _on_disconnect
    client.connect_async(
        os.getenv("MQTT_HOST", "192.168.10.66"),
        int(os.getenv("MQTT_PORT", "8883")),
        keepalive=60,
    )
    client.loop_start()
    _client = client
    logger.info("MQTT consumer started")
    return True


def stop_mqtt_consumer() -> None:
    global _client, _reconnect_timer
    if _reconnect_timer:
        _reconnect_timer.cancel()
        _reconnect_timer = None
    if _client:
        _client.disconnect()
        _client.loop_stop()
        _client = None


def publish_message(topic: str, payload: str, retain: bool = False) -> bool:
    client = _client
    if client is None or not client.is_connected():
        logger.warning("MQTT publish skipped while disconnected: %s", topic)
        return False
    result = client.publish(topic, payload=payload, qos=1, retain=retain)
    return result.rc == mqtt.MQTT_ERR_SUCCESS


def _on_connect(client, _userdata, _flags, reason_code, _properties) -> None:
    if reason_code.is_failure:
        logger.error("MQTT connection rejected: %s", reason_code)
        return
    topics = [
        os.getenv("MQTT_TOPIC", "devices/+/telemetry"),
        os.getenv("MQTT_OTA_STATUS_TOPIC", "devices/+/ota/status"),
    ]
    for topic in topics:
        client.subscribe(topic, qos=1)
    logger.info("MQTT connected and subscribed to %s", ", ".join(topics))


def _on_message(client, _userdata, message) -> None:
    if message.topic.endswith("/ota/status"):
        _on_ota_status(client, message)
        return
    try:
        data, message_id = parse_mqtt_payload(message.topic, message.payload)
    except Exception:
        logger.exception("Discarding invalid MQTT message on %s", message.topic)
        client.ack(message.mid, message.qos)
        return

    db = SessionLocal()
    try:
        ingest_sensor_data(data, db, message_id=message_id)
        client.ack(message.mid, message.qos)
    except Exception:
        db.rollback()
        logger.exception("MQTT ingestion failed; reconnecting for QoS redelivery")
        _schedule_reconnect(client)
    finally:
        db.close()


def _on_ota_status(client, message) -> None:
    try:
        uid, status = parse_ota_status_payload(message.topic, message.payload)
    except Exception:
        logger.exception("Discarding invalid OTA status on %s", message.topic)
        client.ack(message.mid, message.qos)
        return

    db = SessionLocal()
    try:
        from app.ota_service import process_status

        process_status(uid, status, db)
        client.ack(message.mid, message.qos)
        if status.state in {"success", "cancelled"}:
            publish_message(f"devices/{uid}/ota/desired", "", retain=True)
    except ValueError:
        db.rollback()
        logger.exception("Discarding unauthorized or inconsistent OTA status on %s", message.topic)
        client.ack(message.mid, message.qos)
    except Exception:
        db.rollback()
        logger.exception("OTA status processing failed; reconnecting for QoS redelivery")
        _schedule_reconnect(client)
    finally:
        db.close()


def _on_disconnect(_client, _userdata, _flags, reason_code, _properties) -> None:
    if reason_code != 0:
        logger.warning("MQTT disconnected unexpectedly: %s", reason_code)


def _schedule_reconnect(client) -> None:
    global _reconnect_timer
    client.disconnect()
    if _reconnect_timer and _reconnect_timer.is_alive():
        return

    def reconnect():
        global _reconnect_timer
        _reconnect_timer = None
        try:
            client.reconnect()
        except Exception:
            logger.exception("MQTT reconnect failed")
            _schedule_reconnect(client)

    _reconnect_timer = threading.Timer(5, reconnect)
    _reconnect_timer.daemon = True
    _reconnect_timer.start()
