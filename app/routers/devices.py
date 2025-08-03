from fastapi import APIRouter, Depends, HTTPException, status  
from sqlalchemy.orm import Session
from app import models, schemas, database, auth
from pydantic import BaseModel, Field
from typing import List, Optional
from app.auth import get_current_user

router = APIRouter(prefix="/devices", tags=["Devices"])

@router.post("/", response_model=schemas.DeviceResponse)
def add_device(
    device: schemas.DeviceCreate,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    # Cek apakah device ada di database
    db_device = db.query(models.Device).filter(models.Device.uid == device.uid).first()
    
    if not db_device:
        raise HTTPException(status_code=404, detail="Device ID not found")
    
    # Cek kepemilikan device
    if db_device.user_id:
        if db_device.user_id == current_user.id:
            raise HTTPException(status_code=400, detail="Device already registered to your account")
        raise HTTPException(status_code=403, detail="Device registered by another user")
    
    # Update data device
    db_device.name = device.name
    db_device.user_id = current_user.id
    
    db.commit()
    db.refresh(db_device)
    return db_device

@router.get("/", response_model=List[schemas.DeviceResponse])
def get_devices(
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    return db.query(models.Device).filter(models.Device.user_id == current_user.id).all()

@router.delete("/{device_uid}")
def remove_device(
    device_uid: str,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    device = db.query(models.Device).filter(
        models.Device.uid == device_uid,
        models.Device.user_id == current_user.id
    ).first()
    
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    
    # Reset kepemilikan device
    device.user_id = None
    device.name = None
    db.commit()
    
    return {"message": "Device removed successfully"}

# TAMBAHKAN MODEL UNTUK UPDATE
class DeviceUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    connection_interval: Optional[int] = Field(None, ge=1, le=60)

@router.put("/{device_id}", response_model=schemas.DeviceResponse)
def update_device(
    device_id: int,
    device_update: DeviceUpdate,  # Gunakan model baru ini
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(database.get_db)
):
    device = db.query(models.Device).filter(
        models.Device.id == device_id,
        models.Device.user_id == current_user.id
    ).first()
    
    if not device:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Device not found"
        )
    
    # Update name if provided
    if device_update.name is not None:
        device.name = device_update.name
    
    # Update connection interval if provided
    if device_update.connection_interval is not None:
        device.connection_interval = device_update.connection_interval
    
    db.commit()
    db.refresh(device)
    return device

class MoveDeviceRequest(BaseModel):
    target_kolam_id: int = Field(..., gt=0, description="ID kolam tujuan")

@router.post("/{device_id}/move", status_code=status.HTTP_200_OK, response_model=schemas.KolamResponse)
def move_device_to_kolam(
    device_id: int,
    move_request: MoveDeviceRequest,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(database.get_db)
):
    # Dapatkan device yang akan dipindahkan
    device = db.query(models.Device).filter(
        models.Device.id == device_id,
        models.Device.user_id == current_user.id
    ).first()
    
    if not device:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Device not found"
        )
    
    # Dapatkan kolam tujuan
    target_kolam = db.query(models.Kolam).filter(
        models.Kolam.id == move_request.target_kolam_id,
        models.Tambak.user_id == current_user.id  # Pastikan user pemilik tambak
    ).join(models.Tambak).first()
    
    if not target_kolam:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Target kolam not found or you don't have permission"
        )
    
    # Cek jika device sudah terpasang di kolam lain
    current_kolam = db.query(models.Kolam).filter(
        models.Kolam.device_id == device_id
    ).first()
    
    # Jika device saat ini terpasang di kolam, lepaskan
    if current_kolam:
        current_kolam.device_id = None
        db.add(current_kolam)
    
    # Cek jika kolam tujuan sudah memiliki device
    if target_kolam.device_id:
        # Lepaskan device yang saat ini terpasang di kolam tujuan
        old_device = db.query(models.Device).get(target_kolam.device_id)
        if old_device:
            old_device.kolam = None
    
    # Pasangkan device ke kolam tujuan
    target_kolam.device_id = device_id
    db.add(target_kolam)
    
    db.commit()
    db.refresh(target_kolam)
    
    return target_kolam

@router.get("/status/", response_model=schemas.DeviceStatusResponse)
def get_devices_status(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(database.get_db)
):
    devices = db.query(models.Device).filter(
        models.Device.user_id == current_user.id
    ).all()
    
    status_count = {
        'online': 0,
        'offline': 0,
        'maintenance': 0
    }
    
    for device in devices:
        status_count[device.status] += 1
    
    return {
        'online': status_count['online'],
        'offline': status_count['offline'],
        'maintenance': status_count['maintenance'],
        'devices': devices
    }

@router.put("/{device_id}/maintenance", status_code=status.HTTP_204_NO_CONTENT)
def set_maintenance_mode(
    device_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(database.get_db)
):
    device = db.query(models.Device).filter(
        models.Device.id == device_id,
        models.Device.user_id == current_user.id
    ).first()
    
    if not device:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Device not found"
        )
    
    device.status = 'maintenance'
    db.commit()
    return None

@router.put("/{device_id}/online", status_code=status.HTTP_204_NO_CONTENT)
def set_online_mode(
    device_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(database.get_db)
):
    device = db.query(models.Device).filter(
        models.Device.id == device_id,
        models.Device.user_id == current_user.id
    ).first()
    
    if not device:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Device not found"
        )
    
    device.status = 'online'
    device.last_seen = datetime.utcnow()
    db.commit()
    return None

@router.put("/{device_id}/interval", status_code=status.HTTP_204_NO_CONTENT)
def update_connection_interval(
    device_id: int,
    interval: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(database.get_db)
):
    if interval < 1 or interval > 60:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Interval must be between 1 and 60 minutes"
        )
    
    device = db.query(models.Device).filter(
        models.Device.id == device_id,
        models.Device.user_id == current_user.id
    ).first()
    
    if not device:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Device not found"
        )
    
    device.connection_interval = interval
    db.commit()
    return None