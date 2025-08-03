from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from datetime import datetime
from app import models, schemas, database
from typing import List, Optional

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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Device not found"
        )
    
    # Update device status and last seen
    device.last_seen = datetime.utcnow()
    device.status = 'online'
    db.add(device)
    
    sensor_data = models.SensorData(
        device_id=device.id,
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
    sensor_data = db.query(models.SensorData).filter(
        models.SensorData.device_id == device.id
    ).all()

    return sensor_data