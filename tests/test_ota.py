import tempfile
import unittest
import base64
import hashlib
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import HTTPException, UploadFile
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models, schemas
from app.database import Base
from app.ota_service import desired_payload, new_download_token, process_status
from app.routers import ota


class OtaTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.admin = models.User(
            name="Admin",
            email="admin@example.com",
            password_hash="hash",
            role="admin",
        )
        self.device = models.Device(uid="AER2023AQ0029", status="offline")
        self.db.add_all([self.admin, self.device])
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _release(self, artifact_filename="release.bin"):
        release = models.FirmwareRelease(
            version="2.1.0",
            status="ready",
            artifact_filename=artifact_filename,
            sha256="a" * 64,
            size_bytes=1024,
            signature=base64.b64encode(b"test-signature").decode("ascii"),
            signing_key_id="test-key",
            created_by=self.admin.id,
        )
        self.db.add(release)
        self.db.commit()
        return release

    def _assignment(self):
        release = self._release()
        token, token_hash = new_download_token()
        assignment = models.DeviceOtaAssignment(
            device_id=self.device.id,
            release_id=release.id,
            requested_by=self.admin.id,
            download_token_hash=token_hash,
        )
        self.db.add(assignment)
        self.db.commit()
        self.db.refresh(assignment)
        return assignment, token

    def test_desired_payload_uses_uid_assignment_and_sha256(self):
        assignment, token = self._assignment()

        payload = desired_payload(assignment, token)

        self.assertEqual(payload["assignment_id"], assignment.id)
        self.assertEqual(payload["version"], "2.1.0")
        self.assertEqual(payload["sha256"], "a" * 64)
        self.assertEqual(payload["signing_key_id"], "test-key")
        self.assertTrue(payload["signature"])
        self.assertNotEqual(assignment.download_token_hash, token)

    def test_ota_status_is_idempotent_and_updates_device_version(self):
        assignment, _ = self._assignment()
        payload = schemas.OtaStatusMessage.model_validate({
            "schema": 1,
            "message_id": "ota-1",
            "assignment_id": assignment.id,
            "running_version": "2.1.0",
            "target_version": "2.1.0",
            "state": "success",
            "progress": 100,
        })

        self.assertTrue(process_status(self.device.uid, payload, self.db))
        self.assertFalse(process_status(self.device.uid, payload, self.db))

        self.db.refresh(self.device)
        self.db.refresh(assignment)
        self.assertEqual(self.device.current_firmware_version, "2.1.0")
        self.assertEqual(assignment.state, "success")
        self.assertEqual(self.db.query(models.DeviceOtaEvent).count(), 1)

    def test_status_from_another_uid_is_rejected(self):
        assignment, _ = self._assignment()
        payload = schemas.OtaStatusMessage.model_validate({
            "schema": 1,
            "message_id": "ota-2",
            "assignment_id": assignment.id,
            "running_version": "2.0.0",
            "target_version": "2.1.0",
            "state": "downloading",
        })

        with self.assertRaisesRegex(ValueError, "does not belong"):
            process_status("AER2023AQ0030", payload, self.db)

    def test_download_retry_can_return_to_deferred(self):
        assignment, _ = self._assignment()
        downloading = schemas.OtaStatusMessage.model_validate({
            "schema": 1,
            "message_id": "ota-download-1",
            "assignment_id": assignment.id,
            "running_version": "2.0.0",
            "target_version": "2.1.0",
            "state": "downloading",
            "progress": 10,
        })
        deferred = schemas.OtaStatusMessage.model_validate({
            "schema": 1,
            "message_id": "ota-retry-1",
            "assignment_id": assignment.id,
            "running_version": "2.0.0",
            "target_version": "2.1.0",
            "state": "deferred",
            "error_code": "HTTP_TIMEOUT",
        })

        self.assertTrue(process_status(self.device.uid, downloading, self.db))
        self.assertTrue(process_status(self.device.uid, deferred, self.db))
        self.db.refresh(assignment)
        self.assertEqual(assignment.state, "deferred")
        self.assertEqual(assignment.attempt_count, 1)

    def test_upload_is_draft_and_publish_rechecks_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            image = b"firmware-image"
            private_key = ec.generate_private_key(ec.SECP256R1())
            public_key_path = Path(directory) / "public.pem"
            public_key_path.write_bytes(private_key.public_key().public_bytes(
                serialization.Encoding.PEM,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            ))
            signature_bytes = private_key.sign(image, ec.ECDSA(hashes.SHA256()))
            artifact = UploadFile(filename="firmware.bin", file=BytesIO(image))
            signature = UploadFile(filename="firmware.sig", file=BytesIO(signature_bytes))
            with patch.object(ota, "OTA_ARTIFACT_DIR", Path(directory)), patch.object(
                ota, "OTA_SIGNING_PUBLIC_KEY_PATH", public_key_path
            ):
                release = ota.upload_release(
                    "2.2.0", "test", artifact, signature, self.admin, self.db
                )
                self.assertEqual(release.status, "draft")
                stored = Path(directory) / release.artifact_filename
                self.assertTrue(stored.is_file())

                with patch("app.routers.ota.artifact_path", return_value=stored):
                    published = ota.publish_release(release.id, self.admin, self.db)
                self.assertEqual(published.status, "ready")

    def test_factory_artifact_is_signed_published_and_downloadable_by_admin(self):
        with tempfile.TemporaryDirectory() as directory:
            image = b"firmware-image"
            factory_image = b"factory-image"
            private_key = ec.generate_private_key(ec.SECP256R1())
            public_key_path = Path(directory) / "public.pem"
            public_key_path.write_bytes(private_key.public_key().public_bytes(
                serialization.Encoding.PEM,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            ))
            artifact = UploadFile(filename="firmware.bin", file=BytesIO(image))
            signature = UploadFile(
                filename="firmware.sig",
                file=BytesIO(private_key.sign(image, ec.ECDSA(hashes.SHA256()))),
            )
            factory_artifact = UploadFile(filename="factory.bin", file=BytesIO(factory_image))
            factory_signature = UploadFile(
                filename="factory.sig",
                file=BytesIO(private_key.sign(factory_image, ec.ECDSA(hashes.SHA256()))),
            )
            with patch.object(ota, "OTA_ARTIFACT_DIR", Path(directory)), patch.object(
                ota, "OTA_SIGNING_PUBLIC_KEY_PATH", public_key_path
            ):
                release = ota.upload_release(
                    "2.3.0", "factory", artifact, signature, self.admin, self.db,
                    factory_artifact, factory_signature, True,
                )
                self.assertTrue(release.factory_only)
                self.assertEqual(release.factory_sha256, hashlib.sha256(factory_image).hexdigest())
                stored = Path(directory) / release.artifact_filename
                factory_stored = Path(directory) / release.factory_artifact_filename
                with patch("app.routers.ota.artifact_path", return_value=stored), patch(
                    "app.routers.ota.factory_artifact_path", return_value=factory_stored
                ):
                    published = ota.publish_release(release.id, self.admin, self.db)
                    response = ota.download_factory_artifact(release.id, self.admin, self.db)
                self.assertEqual(published.status, "ready")
                self.assertEqual(response.headers["x-artifact-sha256"], release.factory_sha256)
                with self.assertRaisesRegex(HTTPException, "Factory-only"):
                    ota.create_assignments(
                        schemas.OtaAssignmentCreate(release_id=release.id, device_ids=[self.device.id]),
                        self.admin,
                        self.db,
                    )

    def test_artifact_token_is_bound_to_assignment(self):
        assignment, token = self._assignment()
        with tempfile.TemporaryDirectory() as directory:
            stored = Path(directory) / "release.bin"
            stored.write_bytes(b"x" * 1024)
            with patch("app.routers.ota.artifact_path", return_value=stored):
                response = ota.download_artifact(
                    assignment.release_id,
                    f"Bearer {token}",
                    self.db,
                )
                self.assertEqual(response.media_type, "application/octet-stream")

                with self.assertRaises(HTTPException) as context:
                    ota.download_artifact(assignment.release_id, "Bearer wrong", self.db)
                self.assertEqual(context.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()
