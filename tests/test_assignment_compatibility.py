import importlib
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models, schemas
from app.assignments import replace_active_assignment
from app.database import Base


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
        unowned = sensor_router.create_sensor_data(payload, self.db)
        self.assertIsNone(unowned.assignment_id)

        self.device.user_id = self.user.id
        assignment = replace_active_assignment(self.db, self.device)
        self.db.commit()
        owned = sensor_router.create_sensor_data(payload, self.db)
        self.assertEqual(owned.assignment_id, assignment.id)

        response = schemas.SensorDataResponse.model_validate(owned)
        self.assertNotIn("assignment_id", response.model_dump())


if __name__ == "__main__":
    unittest.main()
