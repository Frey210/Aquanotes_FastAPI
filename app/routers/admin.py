from fastapi import APIRouter, Depends, HTTPException, Header, status
from sqlalchemy.orm import Session
import os
import hmac
from app import models, schemas, database
from typing import List

router = APIRouter(prefix="/admin", tags=["Administrator"])

# Dapatkan API Key dari environment variable
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY")

def _valid_admin_key(received_key: str | None) -> bool:
    return bool(
        ADMIN_API_KEY
        and received_key
        and hmac.compare_digest(received_key, ADMIN_API_KEY)
    )

@router.post("/devices", response_model=schemas.DeviceResponse)
def register_device(
    device: schemas.DeviceRegister,
    db: Session = Depends(database.get_db),
    x_api_key: str = Header(None, alias="X-API-Key")
):
    if not _valid_admin_key(x_api_key):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API Key",
            headers={"WWW-Authenticate": "APIKey"}
        )
    
    # Cek apakah UID sudah terdaftar
    existing = db.query(models.Device).filter(
        models.Device.uid == device.uid
    ).first()
    
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Device UID already registered"
        )
    
    # Buat device baru tanpa pemilik
    new_device = models.Device(uid=device.uid)
    db.add(new_device)
    db.commit()
    db.refresh(new_device)
    
    return new_device

@router.get("/devices", response_model=List[schemas.AdminDeviceResponse])
def list_devices(
    db: Session = Depends(database.get_db),
    x_api_key: str = Header(None, alias="X-API-Key")
):
    if not _valid_admin_key(x_api_key):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API Key",
            headers={"WWW-Authenticate": "APIKey"}
        )
    
    # Dapatkan semua device dengan informasi user
    devices = db.query(
        models.Device.id,
        models.Device.uid,
        models.Device.name,
        models.Device.user_id,
        models.User.name.label("user_name")
    ).outerjoin(
        models.User, models.Device.user_id == models.User.id
    ).all()
    
    # Format respons
    result = []
    for device in devices:
        result.append({
            "id": device.id,
            "uid": device.uid,
            "name": device.name,
            "user_id": device.user_id,
            "user_name": device.user_name,
            "registered": device.user_id is not None
        })
    
    return result
