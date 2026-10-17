import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models
from app.database import Base
from app.routers.monitoring import get_parameter_history


class ParameterHistoryTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.user = SimpleNamespace(id=1, role="user")
        self.db.add(models.Device(id=1, uid="test-device", user_id=1))
        self.db.add_all([
            models.DeviceAssignment(id=1, device_id=1, user_id=1),
            models.DeviceAssignment(id=2, device_id=1, user_id=2, ended_at=datetime(2026, 2, 2)),
        ])
        for i in range(40):
            self.db.add(models.SensorData(id=i+1, device_id=1, assignment_id=1,
                timestamp=datetime(2026, 1, 1) + timedelta(seconds=i),
                suhu=0 if i == 0 else (20+i if i < 6 and i != 3 else None)))
        self.db.add(models.SensorData(id=100, device_id=1, assignment_id=2,
            timestamp=datetime(2026, 2, 1), suhu=99))
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def history(self, **kwargs):
        return get_parameter_history(device_id=1, parameter="suhu", limit=4,
            before_id=kwargs.get("before_id"), db=self.db, current_user=kwargs.get("user", self.user))

    def test_finds_old_values_preserves_null_and_zero_and_paginates(self):
        page = self.history()
        self.assertEqual([r.suhu for r in page["readings"]], [22, None, 24, 25])
        self.assertEqual(page["next_before_id"], 3)
        older = self.history(before_id=3)
        self.assertEqual([r.suhu for r in older["readings"]], [0, 21])
        self.assertIsNone(older["next_before_id"])

    def test_ownership_and_cursor_do_not_expose_other_assignments(self):
        with self.assertRaises(HTTPException) as denied:
            self.history(user=SimpleNamespace(id=2, role="user"))
        self.assertEqual(denied.exception.status_code, 404)
        with self.assertRaises(HTTPException):
            self.history(before_id=100)
        admin = self.history(user=SimpleNamespace(id=3, role="admin"))
        self.assertEqual(admin["readings"][-1].suhu, 99)

    def test_unavailable_parameter_returns_empty_and_tied_timestamps_are_not_lost(self):
        empty = get_parameter_history(1, "ph", 24, None, self.db, self.user)
        self.assertEqual(empty["readings"], [])
        self.db.add(models.SensorData(id=41, device_id=1, assignment_id=1,
            timestamp=datetime(2026, 1, 1) + timedelta(seconds=5), suhu=26))
        self.db.commit()
        latest = get_parameter_history(1, "suhu", 1, None, self.db, self.user)
        self.assertEqual(latest["readings"][-1].suhu, 26)
        previous = self.history(before_id=latest["next_before_id"])
        self.assertEqual(previous["readings"][-1].suhu, 25)
