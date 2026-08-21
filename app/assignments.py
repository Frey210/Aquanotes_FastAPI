from datetime import datetime

from sqlalchemy.orm import Session

from app import models


def get_active_assignment(db: Session, device_id: int):
    return db.query(models.DeviceAssignment).filter(
        models.DeviceAssignment.device_id == device_id,
        models.DeviceAssignment.ended_at.is_(None),
    ).first()


def replace_active_assignment(db: Session, device, kolam=None, *, legacy=False):
    """Close the current period and create the device's current ownership context."""
    current = get_active_assignment(db, device.id)
    kolam_id = kolam.id if kolam else None
    tambak_id = kolam.tambak_id if kolam else None

    if current and (
        current.user_id,
        current.kolam_id,
        current.tambak_id,
    ) == (device.user_id, kolam_id, tambak_id):
        return current

    now = datetime.utcnow()
    if current:
        current.ended_at = now
        db.flush()

    if device.user_id is None:
        return None

    assignment = models.DeviceAssignment(
        device_id=device.id,
        user_id=device.user_id,
        kolam_id=kolam_id,
        tambak_id=tambak_id,
        started_at=now,
        is_legacy=legacy,
    )
    db.add(assignment)
    db.flush()
    return assignment
