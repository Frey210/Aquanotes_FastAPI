from fastapi import APIRouter, Depends, HTTPException, status
import logging
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from app import models, schemas, database, auth
from typing import List, Optional
from app.auth import get_current_user
from pydantic import BaseModel, Field

router = APIRouter(prefix="/kolam", tags=["Kolam"])
logger = logging.getLogger(__name__)

@router.post("/", response_model=schemas.KolamResponse)
def create_kolam(
    kolam: schemas.KolamCreate,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    # Validasi kepemilikan tambak
    tambak = db.query(models.Tambak).filter(
        models.Tambak.id == kolam.tambak_id,
        models.Tambak.user_id == current_user.id
    ).first()
    
    if not tambak:
        raise HTTPException(status_code=403, detail="Invalid tambak")
    
    # Validasi device
    device = db.query(models.Device).filter(
        models.Device.id == kolam.device_id,
        models.Device.user_id == current_user.id,
        models.Device.kolam == None
    ).first()
    
    if not device:
        raise HTTPException(status_code=400, detail="Invalid device")
    
    new_kolam = models.Kolam(**kolam.dict())
    db.add(new_kolam)
    db.commit()
    db.refresh(new_kolam)
    return new_kolam

@router.get("/", response_model=List[schemas.KolamResponse])
def get_kolam(
    tambak_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    return db.query(models.Kolam).join(models.Tambak).filter(
        models.Tambak.user_id == current_user.id,
        models.Kolam.tambak_id == tambak_id
    ).all()

@router.delete("/{kolam_id}")
def delete_kolam(
    kolam_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    kolam = db.query(models.Kolam).join(models.Tambak).filter(
        models.Kolam.id == kolam_id,
        models.Tambak.user_id == current_user.id
    ).first()
    
    if not kolam:
        raise HTTPException(status_code=404, detail="Kolam not found")
    try:
        kolam.device_id = None
        db.flush()
        db.delete(kolam)
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        logger.exception("Failed to delete kolam_id=%s", kolam_id)
        raise HTTPException(status_code=500, detail="Failed to delete kolam")
    return {"message": "Kolam deleted successfully"}
    
class KolamUpdate(BaseModel):
    nama: Optional[str] = Field(None, min_length=1, max_length=100)
    tipe: Optional[str] = Field(None, min_length=1, max_length=50)
    panjang: Optional[float] = Field(None, gt=0)
    lebar: Optional[float] = Field(None, gt=0)
    kedalaman: Optional[float] = Field(None, gt=0)
    komoditas: Optional[str] = Field(None, min_length=1, max_length=100)
    tambak_id: Optional[int] = Field(None, gt=0)
    device_id: Optional[int] = Field(None, gt=0)

@router.put("/{kolam_id}", response_model=schemas.KolamResponse)
def update_kolam(
    kolam_id: int,
    kolam_update: KolamUpdate,  # Gunakan model baru ini
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(database.get_db)
):
    # Dapatkan kolam yang akan diupdate
    db_kolam = db.query(models.Kolam).filter(
        models.Kolam.id == kolam_id,
        models.Tambak.user_id == current_user.id
    ).join(models.Tambak).first()

    if not db_kolam:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Kolam not found or you don't have permission"
        )
    
    # Verifikasi tambak (jika diubah)
    if kolam_update.tambak_id and kolam_update.tambak_id != db_kolam.tambak_id:
        tambak = db.query(models.Tambak).filter(
            models.Tambak.id == kolam_update.tambak_id,
            models.Tambak.user_id == current_user.id
        ).first()
        
        if not tambak:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Tambak not found or you don't have permission"
            )
    
    # Verifikasi device (jika diubah)
    if kolam_update.device_id is not None and kolam_update.device_id != db_kolam.device_id:
        if kolam_update.device_id:
            device = db.query(models.Device).filter(
                models.Device.id == kolam_update.device_id,
                models.Device.user_id == current_user.id
            ).first()
            
            if not device:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Device not found or you don't have permission"
                )
            
            # Cek jika device sudah digunakan di kolam lain
            existing_kolam = db.query(models.Kolam).filter(
                models.Kolam.device_id == kolam_update.device_id,
                models.Kolam.id != kolam_id
            ).first()
            
            if existing_kolam:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Device already assigned to another kolam"
                )
        else:
            # Jika device_id di-set menjadi null
            kolam_update.device_id = None

    # Update fields
    for field, value in kolam_update.dict(exclude_unset=True).items():
        setattr(db_kolam, field, value)

    db.commit()
    db.refresh(db_kolam)
    return db_kolam
