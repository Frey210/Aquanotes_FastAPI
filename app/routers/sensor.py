from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from copy import copy
from datetime import datetime
from app import models, schemas, database
from typing import List, Optional
from app.assignments import get_active_assignment
from app.device_state import apply_scheduled_deactivation
from app.timezones import utc_to_tambak_time

router = APIRouter(prefix="/sensor", tags=["Sensor Data"])

@router.post("/", response_model=schemas.SensorDataResponse)
def create_sensor_data(
    data: schemas.SensorDataCreate,
    db: Session = Depends(database.get_db)
):
    device = db.query(models.Device).filter(
        models.Device.uid == data.uid
    ).first()
    
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    received_at = datetime.utcnow()
    device_timestamp = received_at

    scheduled_applied = apply_scheduled_deactivation(device)
    if device.status in {"maintenance", "inactive"}:
        if scheduled_applied:
            db.commit()
        # Preserve the deployed IoT 200/response contract while intentionally not storing the reading.
        return schemas.SensorDataResponse(
            id=0,
            device_id=device.id,
            timestamp=device_timestamp,
            suhu=data.suhu,
            ph=data.ph,
            do=data.do,
            tds=data.tds,
            ammonia=data.ammonia,
            salinitas=data.salinitas,
        )
    
    # Update device status and last seen
    device.last_seen = received_at
    device.status = 'online'
    db.add(device)
    
    assignment = get_active_assignment(db, device.id)
    sensor_data = models.SensorData(
        device_id=device.id,
        assignment_id=assignment.id if assignment else None,
        timestamp=device_timestamp,
        suhu=data.suhu,
        ph=data.ph,
        do=data.do,
        tds=data.tds,
        ammonia=data.ammonia,
        salinitas=data.salinitas
    )
    
    db.add(sensor_data)
    db.commit()
    db.refresh(sensor_data)
    
    return sensor_data

from fastapi import Depends, HTTPException, status
from app.auth import get_current_user

@router.get("/", response_model=List[schemas.SensorDataResponse])
def get_sensor_data(
    uid: str = Query(..., description="UID perangkat"),
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user)  # Verifikasi token
):
    """
    Mendapatkan data sensor DENGAN otorisasi.
    Hanya pemilik device yang bisa akses datanya.
    """
    
    # 1. Cari device dan verifikasi kepemilikan
    device = db.query(models.Device).filter(
        models.Device.uid == uid,
        models.Device.user_id == current_user.id  # Pastikan device milik user
    ).first()

    if not device:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Device tidak ditemukan atau tidak memiliki akses"
        )

    # 2. Query data
    sensor_data = db.query(models.SensorData).join(
        models.DeviceAssignment
    ).filter(
        models.SensorData.device_id == device.id,
        models.DeviceAssignment.user_id == current_user.id,
    ).all()

    tambaks = {
        tambak.id: tambak
        for tambak in db.query(models.Tambak).filter(models.Tambak.user_id == current_user.id)
    }
    fallback_tambak = device.kolam.tambak if device.kolam else None
    for index, data in enumerate(sensor_data):
        localized = copy(data)
        localized.timestamp = utc_to_tambak_time(
            data.timestamp,
            tambaks.get(data.assignment.tambak_id) if data.assignment else fallback_tambak,
        )
        sensor_data[index] = localized

    return sensor_data
