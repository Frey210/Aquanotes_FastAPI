from sqlalchemy.orm import Session
from app import models, schemas, auth
from app.auth import get_password_hash, verify_password
from fastapi import HTTPException, status

# === USER ===
def create_user(db: Session, user: schemas.UserCreate):
    db_user = db.query(models.User).filter(models.User.email == user.email).first()
    if db_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )
    hashed_password = get_password_hash(user.password)
    db_user = models.User(
        username=user.username,
        email=user.email,
        password_hash=hashed_password,
        tambak_name=user.tambak_name,
        tambak_location=user.tambak_location
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user

def authenticate_user(db: Session, email: str, password: str):
    db_user = db.query(models.User).filter(models.User.email == email).first()
    if not db_user or not verify_password(password, db_user.password_hash):
        return False
    return db_user

# === DEVICE ===
def create_device(db: Session, device: schemas.DeviceCreate, user_id: int):
    db_device = db.query(models.Device).filter(models.Device.uid == device.uid).first()
    if db_device:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Device UID already registered"
        )
    db_device = models.Device(uid=device.uid, name=device.name, user_id=user_id)
    db.add(db_device)
    db.commit()
    db.refresh(db_device)
    return db_device

def get_device_by_uid(db: Session, uid: str):
    return db.query(models.Device).filter(models.Device.uid == uid).first()

# === SENSOR DATA ===
def create_sensor_data(db: Session, sensor_data: schemas.SensorDataCreate, device_id: int):
    db_sensor_data = models.SensorData(
        device_id=device_id,
        suhu=sensor_data.suhu,
        ph=sensor_data.ph,
        do=sensor_data.do,
        tds=sensor_data.tds,
        ammonia=sensor_data.ammonia,
        salinitas=sensor_data.salinitas
    )
    db.add(db_sensor_data)
    db.commit()
    db.refresh(db_sensor_data)
    return db_sensor_data

def get_sensor_data_by_device(db: Session, device_id: int, limit: int = 100):
    return db.query(models.SensorData).filter(models.SensorData.device_id == device_id).limit(limit).all()
