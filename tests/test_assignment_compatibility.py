import importlib
import sys
import tempfile
import types
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models, schemas
from app.assignments import replace_active_assignment
from app.database import Base
from app.timezones import tambak_time_to_utc, utc_to_tambak_time


fake_auth = types.ModuleType("app.auth")
fake_auth.get_current_user = lambda: None

with patch.dict(sys.modules, {"app.auth": fake_auth}):
    sys.modules.pop("app.routers.sensor", None)
    sensor_router = importlib.import_module("app.routers.sensor")


class AssignmentCompatibilityTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.user = models.User(
            name="User", email="user@example.test", password_hash="hash"
        )
        self.device = models.Device(uid="device-1", user_id=None)
        self.db.add_all([self.user, self.device])
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_iot_payload_and_mobile_response_stay_unchanged(self):
        self.assertNotIn("assignment_id", schemas.SensorDataCreate.model_fields)
        self.assertNotIn("assignment_id", schemas.SensorDataResponse.model_fields)

        payload = schemas.SensorDataCreate(
            uid=self.device.uid,
            suhu=27,
            ph=8,
            do=6,
            tds=100,
            ammonia=0,
            salinitas=20,
            timestamp="2026-08-22T10:00:00+08:00",
        )
        before = datetime.utcnow()
        unowned = sensor_router.create_sensor_data(payload, self.db)
        after = datetime.utcnow()
        self.assertIsNone(unowned.assignment_id)
        self.assertLessEqual(before, unowned.timestamp)
        self.assertLessEqual(unowned.timestamp, after)

        self.device.user_id = self.user.id
        assignment = replace_active_assignment(self.db, self.device)
        self.db.commit()
        owned = sensor_router.create_sensor_data(payload, self.db)
        self.assertEqual(owned.assignment_id, assignment.id)

        response = schemas.SensorDataResponse.model_validate(owned)
        self.assertNotIn("assignment_id", response.model_dump())
        self.assertEqual(
            set(response.model_dump()),
            {"id", "device_id", "timestamp", "suhu", "ph", "do", "tds", "ammonia", "salinitas"},
        )

    def test_server_time_is_used_for_old_new_and_failed_ntp_payloads(self):
        values = [None, "", "invalid", 0, 123.5, "2026-09-01T09:02:03+08:00"]
        for value in values:
            with self.subTest(timestamp=value):
                payload = schemas.SensorDataCreate(
                    uid=self.device.uid,
                    suhu=27,
                    ph=8,
                    do=6,
                    tds=100,
                    ammonia=0,
                    salinitas=20,
                    timestamp=value,
                )
                before = datetime.utcnow()
                stored = sensor_router.create_sensor_data(payload, self.db)
                after = datetime.utcnow()
                self.assertLessEqual(before, stored.timestamp)
                self.assertLessEqual(stored.timestamp, after)

        without_timestamp = schemas.SensorDataCreate.model_validate({
            "uid": self.device.uid,
            "suhu": 27,
            "ph": 8,
            "do": 6,
            "tds": 100,
            "ammonia": 0,
            "salinitas": 20,
        })
        self.assertIsNone(without_timestamp.timestamp)

    def test_ammonia_is_optional_without_fabricating_zero(self):
        payload = schemas.SensorDataCreate.model_validate({
            "uid": self.device.uid,
            "suhu": 27,
            "ph": 8,
            "do": 6,
            "tds": 100,
            "salinitas": 20,
        })
        stored = sensor_router.create_sensor_data(payload, self.db)
        self.assertIsNone(stored.ammonia)
        self.assertIsNone(schemas.SensorDataResponse.model_validate(stored).ammonia)

    def test_sensor_time_is_displayed_in_tambak_timezone(self):
        utc_value = datetime(2026, 9, 5, 4, 0)
        for province, expected_hour in [
            ("ACEH", 11),
            ("SULAWESI SELATAN", 12),
            ("PAPUA", 13),
        ]:
            tambak = SimpleNamespace(country="Indonesia", province=province)
            local_value = utc_to_tambak_time(utc_value, tambak)
            self.assertEqual(local_value, datetime(2026, 9, 5, expected_hour, 0))
            self.assertEqual(tambak_time_to_utc(local_value, tambak), utc_value)

    def test_paused_device_keeps_iot_success_contract_without_storing_data(self):
        self.device.status = "maintenance"
        self.db.commit()
        payload = schemas.SensorDataCreate(
            uid=self.device.uid,
            suhu=27,
            ph=8,
            do=6,
            tds=100,
            ammonia=0,
            salinitas=20,
            timestamp="2026-08-22T10:00:00+08:00",
        )

        response = sensor_router.create_sensor_data(payload, self.db)

        self.assertEqual(response.id, 0)
        self.assertEqual(response.device_id, self.device.id)
        self.assertEqual(self.db.query(models.SensorData).count(), 0)


if __name__ == "__main__":
    unittest.main()
