from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
import uuid
from app import models, schemas, database
from app.auth import (
    get_password_hash,
    verify_password,
    security,
    get_current_user,
    create_auth_token
)
from fastapi.security import HTTPAuthorizationCredentials

router = APIRouter(prefix="/users", tags=["Users"])

@router.post("/register", response_model=schemas.UserResponse)
def register(
    user: schemas.UserCreate,
    db: Session = Depends(database.get_db)
):
    existing = db.query(models.User).filter(
        models.User.email == user.email
    ).first()
    
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )
    
    new_user = models.User(
        name=user.name,
        email=user.email,
        password_hash=get_password_hash(user.password)
    )
    
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user

@router.post("/login", response_model=schemas.Token)
def login(
    login_data: schemas.UserLogin,
    db: Session = Depends(database.get_db)
):
    user = db.query(models.User).filter(
        models.User.email == login_data.email
    ).first()
    
    if not user or not verify_password(login_data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password"
        )
    
    token = create_auth_token(db, user.id)
    return {"access_token": token, "token_type": "bearer"}

@router.post("/logout")
def logout(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user)
):
    token = credentials.credentials
    
    db.query(models.AuthToken).filter(
        models.AuthToken.token == token
    ).delete()
    
    db.commit()
    return {
        "message": "Successfully logged out",
        "success": True
    }

@router.get("/me", response_model=schemas.UserResponse)
def get_current_user_info(
    current_user: models.User = Depends(get_current_user)
):
    return current_user

@router.post("/fcm-token", status_code=status.HTTP_200_OK)
def update_fcm_token(
    token_data: schemas.FCMTokenUpdate,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user)
):
    """
    Update FCM token untuk notifikasi push
    
    Args:
        token_data: Objek berisi token FCM
        
    Returns:
        Konfirmasi update berhasil
    """
    # Validasi token tidak kosong
    if not token_data.token or len(token_data.token) < 10:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid FCM token"
        )
    
    # Update token di database
    current_user.fcm_token = token_data.token
    db.commit()
    
    return {
        "message": "FCM token updated successfully",
        "new_token": token_data.token[:10] + "..."  # Return partial token for security
    }

@router.delete("/fcm-token", status_code=status.HTTP_200_OK)
def remove_fcm_token(
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user)
):
    """
    Hapus FCM token (saat logout atau uninstall app)
    """
    current_user.fcm_token = None
    db.commit()
    return {"message": "FCM token removed successfully"}

@router.put("/profile", response_model=schemas.UserResponse)
def update_user_profile(
    profile_data: schemas.UserProfileUpdate,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user)
):
    """
    Update profil user (nama, password)
    """
    # Update nama jika ada
    if profile_data.name:
        current_user.name = profile_data.name
    
    # Update password jika ada
    if profile_data.new_password:
        # Verifikasi password lama
        if not verify_password(profile_data.old_password, current_user.password_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect current password"
            )
        
        # Update password baru
        current_user.password_hash = get_password_hash(profile_data.new_password)
    
    db.commit()
    db.refresh(current_user)
    return current_user