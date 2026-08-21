from fastapi import APIRouter, Depends, HTTPException, status
import logging
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from app import models, schemas, database, auth
from pydantic import BaseModel, Field
from app.auth import get_current_user
from typing import List, Optional
from app.assignments import replace_active_assignment

router = APIRouter(prefix="/tambak", tags=["Tambak"])
logger = logging.getLogger(__name__)

@router.post("/", response_model=schemas.TambakResponse)
def create_tambak(
    tambak: schemas.TambakCreate,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    try:
        new_tambak = models.Tambak(
            **tambak.dict(exclude_unset=True),
            user_id=current_user.id  # Pastikan user_id diset
        )
        db.add(new_tambak)
        db.commit()
        db.refresh(new_tambak)
        return new_tambak
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=403,
            detail=f"Gagal membuat tambak: {str(e)}"
        )

@router.get("/", response_model=list[schemas.TambakResponse])
def get_tambak(
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    return db.query(models.Tambak).filter(
        models.Tambak.user_id == current_user.id
    ).all()

@router.delete("/{tambak_id}")
def delete_tambak(
    tambak_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    tambak = db.query(models.Tambak).filter(
        models.Tambak.id == tambak_id,
        models.Tambak.user_id == current_user.id
    ).first()
    
    if not tambak:
        raise HTTPException(status_code=404, detail="Tambak tidak ditemukan")
    
    try:
        for kolam in list(tambak.kolams):
            device = kolam.device
            kolam.device_id = None
            db.flush()
            if device:
                replace_active_assignment(db, device)
            db.delete(kolam)
        db.flush()
        db.delete(tambak)
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        logger.exception("Failed to delete tambak_id=%s", tambak_id)
        raise HTTPException(status_code=500, detail="Failed to delete tambak")
    return {"message": "Tambak berhasil dihapus"}

class TambakUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    country: Optional[str] = Field(None, min_length=1, max_length=100)
    province: Optional[str] = Field(None, min_length=1, max_length=100)
    city: Optional[str] = Field(None, min_length=1, max_length=100)
    district: Optional[str] = Field(None, min_length=1, max_length=100)
    village: Optional[str] = Field(None, min_length=1, max_length=100)
    address: Optional[str] = Field(None, min_length=1, max_length=255)
    cultivation_type: Optional[str] = Field(None, min_length=1, max_length=100)

@router.put("/{tambak_id}", response_model=schemas.TambakResponse)
def update_tambak(
    tambak_id: int,
    tambak_update: TambakUpdate,  # Gunakan model baru ini
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(database.get_db)
):
    tambak = db.query(models.Tambak).filter(
        models.Tambak.id == tambak_id,
        models.Tambak.user_id == current_user.id
    ).first()
    
    if not tambak:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tambak not found"
        )
    
    # Update fields that are provided
    for field, value in tambak_update.dict(exclude_unset=True).items():
        setattr(tambak, field, value)
    
    db.commit()
    db.refresh(tambak)
    return tambak
