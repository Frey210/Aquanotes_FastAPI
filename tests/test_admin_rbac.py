import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import auth, models, schemas
from app.database import Base
from app.device_state import apply_scheduled_deactivation, operational_mode
from app.routers.admin import _connectivity_status, _outside_limit, _sensor_values, admin_users


class AdminRBACTest(unittest.TestCase):
    def test_existing_user_response_contract_does_not_gain_role(self):
        self.assertNotIn("role", schemas.UserResponse.model_fields)
        self.assertIn("role", schemas.UserSessionResponse.model_fields)

    def test_user_cannot_pass_admin_dependency(self):
        with self.assertRaises(HTTPException) as context:
            auth.require_admin(models.User(role="user"))
        self.assertEqual(context.exception.status_code, 403)

    def test_admin_passes_admin_dependency(self):
        admin = models.User(role="admin")
        self.assertIs(auth.require_admin(admin), admin)

    def test_connectivity_is_derived_without_mutating_legacy_status(self):
        now = datetime.utcnow()
        device = models.Device(
            uid="test-device",
            status="maintenance",
            connection_interval=5,
            last_seen=now - timedelta(minutes=6),
        )
        self.assertEqual(_connectivity_status(device, now), "stale")
        self.assertEqual(device.status, "maintenance")

    def test_device_controls_and_parameter_attention(self):
        now = datetime.utcnow()
        device = models.Device(
            uid="scheduled-device",
            status="online",
            deactivation_scheduled_at=now - timedelta(seconds=1),
            temp_min_threshold=26,
            temp_max_threshold=31,
        )
        self.assertTrue(apply_scheduled_deactivation(device, now))
        self.assertEqual(operational_mode(device), "inactive")
        self.assertTrue(_outside_limit(device, "suhu", 32))
        self.assertFalse(_outside_limit(device, "suhu", 28))

    def test_admin_sensor_timestamp_keeps_tambak_offset(self):
        reading = models.SensorData(
            timestamp=datetime(2026, 9, 5, 10, 46, 13),
            suhu=31.8,
            ph=4.08,
            do=6.86,
            tds=3029.5,
            ammonia=0,
            salinitas=3.23,
        )
        tambak = SimpleNamespace(country="Indonesia", province="SULAWESI SELATAN")

        timestamp = _sensor_values(reading, tambak)["timestamp"]

        self.assertEqual(timestamp.isoformat(), "2026-09-05T18:46:13+08:00")

    def test_admin_user_list_exposes_only_safe_account_summary(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        db = sessionmaker(bind=engine)()
        user = models.User(name="User", email="user@example.com", password_hash="secret-hash", email_verified=True)
        db.add(user)
        db.commit()

        result = admin_users(None, None, None, 1, 25, models.User(role="admin"), db)

        self.assertEqual(result["total"], 1)
        self.assertEqual(result["items"][0]["email"], "user@example.com")
        self.assertNotIn("password_hash", result["items"][0])
        self.assertNotIn("fcm_token", result["items"][0])
        db.close()


if __name__ == "__main__":
    unittest.main()
