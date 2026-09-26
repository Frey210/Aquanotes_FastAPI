import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models
from app.database import Base
from app.mqtt_consumer import parse_mqtt_payload
from app.sensor_ingestion import ingest_sensor_data


class MqttIngestionTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.device = models.Device(uid="AER2023AQ0029", status="offline")
        self.db.add(self.device)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_qos_redelivery_is_idempotent(self):
        payload = b'{"message_id":"boot-1:1","suhu":28.5,"ph":null}'
        data, message_id = parse_mqtt_payload(
            "devices/AER2023AQ0029/telemetry",
            payload,
        )
        ingest_sensor_data(data, self.db, message_id=message_id)
        ingest_sensor_data(data, self.db, message_id=message_id)

        self.assertEqual(self.db.query(models.SensorData).count(), 1)
        self.assertEqual(self.db.query(models.MqttIngestReceipt).count(), 1)

    def test_topic_uid_is_authoritative(self):
        with self.assertRaisesRegex(ValueError, "does not match"):
            parse_mqtt_payload(
                "devices/AER2023AQ0029/telemetry",
                b'{"message_id":"boot-1:2","uid":"OTHER"}',
            )


if __name__ == "__main__":
    unittest.main()
