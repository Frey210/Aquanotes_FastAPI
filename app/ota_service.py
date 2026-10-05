import hashlib
import json
import os
import secrets
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app import models, schemas


ACTIVE_STATES = {
    "assigned", "deferred", "downloading", "downloaded", "rebooting", "pending_verify",
}
TERMINAL_STATES = {"success", "failed", "rolled_back", "cancelled"}
STATE_ORDER = {
    "assigned": 0,
    "deferred": 0,
    "downloading": 1,
    "downloaded": 2,
    "rebooting": 3,
    "pending_verify": 4,
    "success": 5,
    "failed": 5,
    "rolled_back": 5,
    "cancelled": 5,
}
OTA_SLOT_SIZE = int(os.getenv("OTA_SLOT_SIZE", str(0x330000)))
OTA_ARTIFACT_DIR = Path(os.getenv("OTA_ARTIFACT_DIR", "/app/ota-artifacts"))
OTA_PUBLIC_BASE_URL = os.getenv("OTA_PUBLIC_BASE_URL", "https://aquanotes.farlabs.my.id/api")


def hash_download_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_download_token() -> tuple[str, str]:
    token = secrets.token_urlsafe(32)
    return token, hash_download_token(token)


def artifact_path(release: models.FirmwareRelease) -> Path:
    path = (OTA_ARTIFACT_DIR / release.artifact_filename).resolve()
    root = OTA_ARTIFACT_DIR.resolve()
    if path.parent != root:
        raise ValueError("Invalid artifact path")
    return path


def assignment_response(assignment: models.DeviceOtaAssignment) -> dict:
    return {
        "id": assignment.id,
        "device_id": assignment.device_id,
        "device_uid": assignment.device.uid,
        "release_id": assignment.release_id,
        "version": assignment.release.version,
        "from_version": assignment.from_version,
        "state": assignment.state,
        "progress": assignment.progress,
        "attempt_count": assignment.attempt_count,
        "last_error_code": assignment.last_error_code,
        "last_error_detail": assignment.last_error_detail,
        "requested_at": assignment.requested_at,
        "started_at": assignment.started_at,
        "completed_at": assignment.completed_at,
        "last_report_at": assignment.last_report_at,
        "is_rollback": assignment.is_rollback,
        "mandatory": assignment.mandatory,
    }


def desired_payload(
    assignment: models.DeviceOtaAssignment,
    token: str,
) -> dict:
    return {
        "schema": 1,
        "assignment_id": assignment.id,
        "release_id": assignment.release_id,
        "version": assignment.release.version,
        "url": f"{OTA_PUBLIC_BASE_URL.rstrip('/')}/ota/artifacts/{assignment.release_id}",
        "download_token": token,
        "sha256": assignment.release.sha256,
        "signature": assignment.release.signature,
        "signing_key_id": assignment.release.signing_key_id,
        "size": assignment.release.size_bytes,
        "mandatory": assignment.mandatory,
        "rollback": assignment.is_rollback,
    }


def publish_desired(
    assignment: models.DeviceOtaAssignment,
    token: str,
) -> bool:
    from app.mqtt_consumer import publish_message

    topic = f"devices/{assignment.device.uid}/ota/desired"
    return publish_message(topic, json.dumps(desired_payload(assignment, token)), retain=True)


def clear_desired(uid: str) -> bool:
    from app.mqtt_consumer import publish_message

    return publish_message(f"devices/{uid}/ota/desired", "", retain=True)


def process_status(uid: str, status: schemas.OtaStatusMessage, db: Session) -> bool:
    assignment = db.get(models.DeviceOtaAssignment, status.assignment_id)
    if not assignment or assignment.device.uid != uid:
        raise ValueError("OTA assignment does not belong to topic UID")
    if status.schema_version != 1:
        raise ValueError("Unsupported OTA status schema")
    if status.target_version != assignment.release.version:
        raise ValueError("OTA target version does not match assignment")

    duplicate = db.query(models.DeviceOtaEvent.id).filter(
        models.DeviceOtaEvent.assignment_id == assignment.id,
        models.DeviceOtaEvent.message_id == status.message_id,
    ).first()
    if duplicate:
        return False

    if assignment.state in TERMINAL_STATES and status.state != assignment.state:
        raise ValueError("OTA assignment is already terminal")
    # A failed download attempt returns to deferred while the device waits for
    # its bounded retry backoff. This is the only intentional non-monotonic
    # transition in the OTA state machine.
    retry_backoff = assignment.state == "downloading" and status.state == "deferred"
    if STATE_ORDER[status.state] < STATE_ORDER[assignment.state] and not retry_backoff:
        raise ValueError("OTA status cannot move backwards")

    now = datetime.utcnow()
    if status.state == "downloading" and assignment.started_at is None:
        assignment.started_at = now
        assignment.attempt_count += 1
    if status.state in TERMINAL_STATES:
        assignment.completed_at = now

    assignment.state = status.state
    assignment.progress = status.progress
    assignment.last_error_code = status.error_code
    assignment.last_error_detail = status.error_detail
    assignment.last_report_at = now
    assignment.device.current_firmware_version = status.running_version
    if status.state == "success":
        assignment.device.current_firmware_version = assignment.release.version

    db.add(models.DeviceOtaEvent(
        assignment_id=assignment.id,
        message_id=status.message_id,
        state=status.state,
        progress=status.progress,
        error_code=status.error_code,
    ))
    db.commit()
    return True
