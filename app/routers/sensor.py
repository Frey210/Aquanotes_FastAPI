from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from copy import copy
from datetime import datetime
from app import models, schemas, database
from typing import List, Optional
from app.sensor_ingestion import ingest_sensor_data
from app.timezones import utc_to_tambak_time

router = APIRouter(prefix="/sensor", tags=["Sensor Data"])

@router.post("/", response_model=schemas.SensorDataResponse)
def create_sensor_data(
    data: schemas.SensorDataCreate,
    db: Session = Depends(database.get_db)
):
    return ingest_sensor_data(data, db)

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
