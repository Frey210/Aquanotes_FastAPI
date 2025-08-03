from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app import models, schemas, database, auth

router = APIRouter(prefix="/devices", tags=["Device Thresholds"])

@router.put("/{device_id}/thresholds", 
           response_model=schemas.DeviceThresholdResponse,
           status_code=status.HTTP_200_OK)
def update_device_thresholds(
    device_id: int,
    thresholds: schemas.ThresholdSettings,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    device = db.query(models.Device).filter(
        models.Device.id == device_id,
        models.Device.user_id == current_user.id
    ).first()
    
    if not device:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Device not found or not owned by user"
        )
    
    # Update threshold settings
    update_data = thresholds.dict(exclude_unset=True)
    for field, value in update_data.items():
        db_field = f"{field}_threshold"
        if hasattr(device, db_field):
            setattr(device, db_field, value)
    
    db.commit()
    db.refresh(device)
    
    return {
        "device_id": device.id,
        "device_name": device.name,
        **thresholds.dict()
    }

@router.get("/{device_id}/thresholds",
           response_model=schemas.DeviceThresholdResponse)
def get_device_thresholds(
    device_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    device = db.query(models.Device).filter(
        models.Device.id == device_id,
        models.Device.user_id == current_user.id
    ).first()
    
    if not device:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Device not found or not owned by user"
        )
    
    # Extract threshold values
    thresholds = {
        "temp_min": device.temp_min_threshold,
        "temp_max": device.temp_max_threshold,
        "ph_min": device.ph_min_threshold,
        "ph_max": device.ph_max_threshold,
        "do_min": device.do_min_threshold,
        "tds_max": device.tds_max_threshold,
        "ammonia_max": device.ammonia_max_threshold,
        "salinitas_min": device.salinitas_min_threshold,
        "salinitas_max": device.salinitas_max_threshold
    }
    
    return {
        "device_id": device.id,
        "device_name": device.name,
        **thresholds
    }