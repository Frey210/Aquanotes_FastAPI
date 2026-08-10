import unittest
import sys
import types

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models

firebase_service = types.ModuleType("app.firebase_service")
firebase_service.send_fcm_notification = lambda *args, **kwargs: True
sys.modules["app.firebase_service"] = firebase_service

from app.background_tasks import _claim_threshold_alert
from app.database import Base


class ThresholdAlertStateTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()

    def tearDown(self):
        self.db.close()

    def claim(self, value, threshold=10.0):
        claimed = _claim_threshold_alert(
            self.db, 31, "tds", "max", threshold, value > threshold
        )
        self.db.commit()
        return claimed

    def test_only_claims_on_transition_or_threshold_change(self):
        self.assertTrue(self.claim(11.0))
        self.assertFalse(self.claim(12.0))
        self.assertFalse(self.claim(9.0))
        self.assertTrue(self.claim(11.0))
        self.assertTrue(self.claim(11.0, threshold=8.0))


if __name__ == "__main__":
    unittest.main()
