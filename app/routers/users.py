from datetime import datetime, timedelta
import hashlib
import secrets
import threading
import time

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session
from app import models, schemas, database
from app.auth import (
    get_password_hash,
    verify_password,
    security,
    get_current_user,
    create_auth_token
)
from fastapi.security import HTTPAuthorizationCredentials
from app.email_service import (
    send_password_reset_email,
    send_safely,
    send_verification_email,
)

router = APIRouter(prefix="/users", tags=["Users"])

_attempts: dict[str, list[float]] = {}
_attempt_lock = threading.Lock()


def _limit(request: Request, scope: str, email: str) -> None:
    now = time.monotonic()
    host = request.client.host if request.client else "unknown"
    limits = ((f"{scope}:ip:{host}", 20), (f"{scope}:email:{email.lower()}", 5))
    # ponytail: in-memory limiter is per process; move to Redis when the API runs multiple workers.
    with _attempt_lock:
        for key in [key for key, values in _attempts.items() if not values or now - values[-1] >= 900]:
            del _attempts[key]
        for key, maximum in limits:
            recent = [value for value in _attempts.get(key, []) if now - value < 900]
            if len(recent) >= maximum:
                raise HTTPException(status_code=429, detail="Terlalu banyak percobaan. Coba lagi dalam 15 menit.")
            _attempts[key] = recent
        for key, _ in limits:
            _attempts[key].append(now)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _new_email_token(db: Session, user_id: int, purpose: str) -> str:
    db.query(models.EmailToken).filter(
        models.EmailToken.user_id == user_id,
        models.EmailToken.purpose == purpose,
        models.EmailToken.used_at.is_(None),
    ).delete(synchronize_session=False)
    token = secrets.token_urlsafe(32)
    db.add(models.EmailToken(
        user_id=user_id,
        token_hash=_token_hash(token),
        purpose=purpose,
        expires_at=datetime.utcnow() + timedelta(minutes=30),
    ))
    return token


def _find_email_token(db: Session, token: str, purpose: str):
    return db.query(models.EmailToken).filter(
        models.EmailToken.token_hash == _token_hash(token),
        models.EmailToken.purpose == purpose,
        models.EmailToken.used_at.is_(None),
        models.EmailToken.expires_at > datetime.utcnow(),
    ).first()


def _create_user(user: schemas.UserCreate, db: Session, email_verified: bool):
    existing = db.query(models.User).filter(models.User.email == user.email).first()
    if existing:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered")
    new_user = models.User(
        name=user.name,
        email=user.email,
        password_hash=get_password_hash(user.password),
        email_verified=email_verified,
    )
    db.add(new_user)
    return new_user

@router.post("/register", response_model=schemas.UserResponse)
def register(
    user: schemas.UserCreate,
    db: Session = Depends(database.get_db)
):
    new_user = _create_user(user, db, email_verified=True)
    db.commit()
    db.refresh(new_user)
    return new_user


@router.post("/register-web", response_model=schemas.MessageResponse, status_code=status.HTTP_201_CREATED)
def register_web(user: schemas.UserCreate, request: Request, db: Session = Depends(database.get_db)):
    _limit(request, "register", user.email)
    new_user = _create_user(user, db, email_verified=False)
    db.flush()
    token = _new_email_token(db, new_user.id, "verify")
    try:
        send_verification_email(new_user.email, new_user.name, token)
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=503, detail="Email verifikasi belum dapat dikirim. Coba lagi.")
    return {"message": "Akun dibuat. Periksa email Anda untuk melakukan verifikasi."}

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


@router.post("/login-web", response_model=schemas.Token)
def login_web(login_data: schemas.UserLogin, db: Session = Depends(database.get_db)):
    user = db.query(models.User).filter(models.User.email == login_data.email).first()
    if not user or not verify_password(login_data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Incorrect email or password")
    if not user.email_verified:
        raise HTTPException(status_code=403, detail="Email belum diverifikasi")
    return {"access_token": create_auth_token(db, user.id), "token_type": "bearer"}


@router.post("/email-verification/request", response_model=schemas.MessageResponse)
def request_email_verification(
    payload: schemas.EmailRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(database.get_db),
):
    _limit(request, "verify", payload.email)
    user = db.query(models.User).filter(models.User.email == payload.email).first()
    if user and not user.email_verified:
        token = _new_email_token(db, user.id, "verify")
        db.commit()
        background_tasks.add_task(send_safely, send_verification_email, user.email, user.name, token)
    return {"message": "Jika akun memerlukan verifikasi, tautan baru akan dikirim ke email tersebut."}


@router.post("/email-verification/confirm", response_model=schemas.MessageResponse)
def confirm_email_verification(payload: schemas.EmailTokenConfirm, db: Session = Depends(database.get_db)):
    email_token = _find_email_token(db, payload.token, "verify")
    if not email_token:
        raise HTTPException(status_code=400, detail="Tautan verifikasi tidak valid atau sudah kedaluwarsa.")
    email_token.user.email_verified = True
    email_token.used_at = datetime.utcnow()
    db.commit()
    return {"message": "Email berhasil diverifikasi. Silakan masuk ke Aquanotes."}


@router.post("/password-reset/request", response_model=schemas.MessageResponse)
def request_password_reset(
    payload: schemas.EmailRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(database.get_db),
):
    _limit(request, "reset", payload.email)
    user = db.query(models.User).filter(models.User.email == payload.email).first()
    if user and user.email_verified:
        token = _new_email_token(db, user.id, "reset")
        db.commit()
        background_tasks.add_task(send_safely, send_password_reset_email, user.email, user.name, token)
    return {"message": "Jika email terdaftar dan sudah diverifikasi, tautan reset akan dikirim."}


@router.post("/password-reset/confirm", response_model=schemas.MessageResponse)
def confirm_password_reset(payload: schemas.PasswordResetConfirm, db: Session = Depends(database.get_db)):
    email_token = _find_email_token(db, payload.token, "reset")
    if not email_token:
        raise HTTPException(status_code=400, detail="Tautan reset tidak valid atau sudah kedaluwarsa.")
    email_token.user.password_hash = get_password_hash(payload.password)
    email_token.used_at = datetime.utcnow()
    db.query(models.AuthToken).filter(models.AuthToken.user_id == email_token.user_id).delete(synchronize_session=False)
    db.commit()
    return {"message": "Password berhasil diubah. Silakan masuk kembali."}

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


@router.get("/session", response_model=schemas.UserSessionResponse)
def get_current_session(
    current_user: models.User = Depends(get_current_user)
):
    return current_user
