import importlib
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

PROJECT_ROOT = str(Path(__file__).resolve().parents[1])
sys.path.insert(0, PROJECT_ROOT)
for module_name in list(sys.modules):
    if module_name == "app" or module_name.startswith("app."):
        del sys.modules[module_name]

import app
from app import models, schemas
from app.database import Base


fake_auth = types.ModuleType("app.auth")
fake_auth.get_current_user = lambda: None

with patch.dict(sys.modules, {"app.auth": fake_auth}):
    sys.modules.pop("app.routers", None)
    sys.modules.pop("app.routers.devices", None)
    sys.modules.pop("app.routers.kolam", None)
    sys.modules.pop("app.routers.tambak", None)
    if hasattr(app, "routers"):
        delattr(app, "routers")
    devices = importlib.import_module("app.routers.devices")
    kolam = importlib.import_module("app.routers.kolam")
    tambak = importlib.import_module("app.routers.tambak")


class DeviceRelationshipTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()

        self.user_1 = models.User(
            id=1, name="User 1", email="u1@example.test", password_hash="hash"
        )
        self.user_2 = models.User(
            id=2, name="User 2", email="u2@example.test", password_hash="hash"
        )
        self.tambak_1 = self._tambak(1, self.user_1.id)
        self.tambak_2 = self._tambak(2, self.user_2.id)
        self.db.add_all([self.user_1, self.user_2, self.tambak_1, self.tambak_2])
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    @staticmethod
    def _tambak(tambak_id, user_id):
        return models.Tambak(
            id=tambak_id,
            name=f"Tambak {tambak_id}",
            country="ID",
            province="Sulawesi Selatan",
            city="Makassar",
            district="Tamalanrea",
            village="Tamalanrea",
            address="Test",
            cultivation_type="Udang",
            user_id=user_id,
        )

    @staticmethod
    def _device(device_id, user_id):
        return models.Device(
            id=device_id,
            uid=f"device-{device_id}",
            name=f"Device {device_id}",
            user_id=user_id,
            temp_min_threshold=20,
            status="online",
            connection_interval=10,
        )

    @staticmethod
    def _kolam(kolam_id, tambak_id, device_id=None):
        return models.Kolam(
            id=kolam_id,
            nama=f"Kolam {kolam_id}",
            tipe="Beton",
            komoditas="Udang",
            tambak_id=tambak_id,
            device_id=device_id,
        )

    def test_remove_detaches_and_resets_device_without_deleting_history(self):
        device = self._device(1, self.user_1.id)
        pond = self._kolam(1, self.tambak_1.id, device.id)
        sensor = models.SensorData(device_id=device.id, suhu=27)
        alert = models.ThresholdAlertState(
            device_id=device.id,
            parameter="suhu",
            threshold_type="min",
            threshold_value=20,
            is_active=True,
        )
        notification = models.Notification(
            user_id=self.user_1.id, device_id=device.id, message="Test"
        )
        self.db.add_all([device, pond, sensor, alert, notification])
        self.db.commit()

        result = devices.remove_device(device.uid, self.db, self.user_1)

        self.db.refresh(device)
        self.db.refresh(pond)
        self.assertEqual(result, {"message": "Device removed successfully"})
        self.assertIsNone(pond.device_id)
        self.assertIsNone(device.user_id)
        self.assertIsNone(device.name)
        self.assertIsNone(device.temp_min_threshold)
        self.assertEqual(device.status, "offline")
        self.assertIsNone(device.last_seen)
        self.assertEqual(device.connection_interval, 5)
        self.assertEqual(self.db.query(models.ThresholdAlertState).count(), 0)
        self.assertEqual(self.db.query(models.SensorData).count(), 1)
        self.assertEqual(self.db.query(models.Notification).count(), 1)

        devices.add_device(
            schemas.DeviceCreate(uid=device.uid, name="Reclaimed"),
            self.db,
            self.user_2,
        )
        self.db.refresh(device)
        self.assertEqual(device.user_id, self.user_2.id)
        self.assertIsNone(device.kolam)

    def test_delete_tambak_removes_its_kolam_but_preserves_device_data(self):
        device = self._device(1, self.user_1.id)
        pond = self._kolam(1, self.tambak_1.id, device.id)
        sensor = models.SensorData(device_id=device.id, suhu=27)
        self.db.add_all([device, pond, sensor])
        self.db.commit()

        result = tambak.delete_tambak(self.tambak_1.id, self.db, self.user_1)

        self.assertEqual(result, {"message": "Tambak berhasil dihapus"})
        self.assertIsNone(self.db.get(models.Tambak, self.tambak_1.id))
        self.assertIsNone(self.db.get(models.Kolam, pond.id))
        self.assertIsNotNone(self.db.get(models.Device, device.id))
        self.assertEqual(self.db.query(models.SensorData).count(), 1)

    def test_delete_kolam_preserves_claimed_device_and_sensor_data(self):
        device = self._device(1, self.user_1.id)
        pond = self._kolam(1, self.tambak_1.id, device.id)
        sensor = models.SensorData(device_id=device.id, suhu=27)
        self.db.add_all([device, pond, sensor])
        self.db.commit()

        result = kolam.delete_kolam(pond.id, self.db, self.user_1)

        self.assertEqual(result, {"message": "Kolam deleted successfully"})
        self.assertIsNone(self.db.get(models.Kolam, pond.id))
        self.assertEqual(self.db.get(models.Device, device.id).user_id, self.user_1.id)
        self.assertEqual(self.db.query(models.SensorData).count(), 1)

    def test_move_replaces_target_device_without_losing_either_history(self):
        moving = self._device(1, self.user_1.id)
        displaced = self._device(2, self.user_1.id)
        source = self._kolam(1, self.tambak_1.id, moving.id)
        target = self._kolam(2, self.tambak_1.id, displaced.id)
        self.db.add_all([
            moving,
            displaced,
            source,
            target,
            models.SensorData(device_id=moving.id, suhu=27),
            models.SensorData(device_id=displaced.id, suhu=28),
        ])
        self.db.commit()

        result = devices.move_device_to_kolam(
            moving.id,
            devices.MoveDeviceRequest(target_kolam_id=target.id),
            self.user_1,
            self.db,
        )

        self.db.refresh(source)
        self.db.refresh(target)
        self.assertEqual(result.id, target.id)
        self.assertIsNone(source.device_id)
        self.assertEqual(target.device_id, moving.id)
        self.assertIsNone(displaced.kolam)
        self.assertEqual(self.db.query(models.SensorData).count(), 2)


if __name__ == "__main__":
    unittest.main()
