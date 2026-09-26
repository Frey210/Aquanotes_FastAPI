from datetime import datetime

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app import models, schemas
from app.assignments import get_active_assignment
from app.device_state import apply_scheduled_deactivation


def ingest_sensor_data(
    data: schemas.SensorDataCreate,
    db: Session,
    *,
    message_id: str | None = None,
):
    device = db.query(models.Device).filter(models.Device.uid == data.uid).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    if message_id:
        receipt = db.query(models.MqttIngestReceipt).filter(
            models.MqttIngestReceipt.device_id == device.id,
            models.MqttIngestReceipt.message_id == message_id,
        ).first()
        if receipt:
            return receipt.sensor_data or _unstored_response(device.id, data)

    received_at = datetime.utcnow()
    scheduled_applied = apply_scheduled_deactivation(device)
    if device.status in {"maintenance", "inactive"}:
        if message_id:
            db.add(models.MqttIngestReceipt(
                device_id=device.id,
                message_id=message_id,
                received_at=received_at,
            ))
        if scheduled_applied or message_id:
            db.commit()
        return _unstored_response(device.id, data, received_at)

    device.last_seen = received_at
    device.status = "online"
    assignment = get_active_assignment(db, device.id)
    reading = models.SensorData(
        device_id=device.id,
        assignment_id=assignment.id if assignment else None,
        timestamp=received_at,
        suhu=data.suhu,
        ph=data.ph,
        do=data.do,
        tds=data.tds,
        ammonia=data.ammonia,
        salinitas=data.salinitas,
    )
    db.add(reading)
    db.flush()
    if message_id:
        db.add(models.MqttIngestReceipt(
            device_id=device.id,
            message_id=message_id,
            sensor_data_id=reading.id,
            received_at=received_at,
        ))
    db.commit()
    db.refresh(reading)
    return reading


def _unstored_response(
    device_id: int,
    data: schemas.SensorDataCreate,
    timestamp: datetime | None = None,
) -> schemas.SensorDataResponse:
    return schemas.SensorDataResponse(
        id=0,
        device_id=device_id,
        timestamp=timestamp or datetime.utcnow(),
        suhu=data.suhu,
        ph=data.ph,
        do=data.do,
        tds=data.tds,
        ammonia=data.ammonia,
        salinitas=data.salinitas,
    )
