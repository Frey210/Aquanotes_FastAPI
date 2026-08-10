from sqlalchemy import Column, Integer, String, Float, ForeignKey, DateTime, Boolean, Index
from sqlalchemy.orm import relationship
from datetime import datetime
from app.database import Base

class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    email = Column(String(100), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    fcm_token = Column(String(255), nullable=True)
    
    devices = relationship("Device", back_populates="owner")
    tambaks = relationship("Tambak", back_populates="owner")
    notifications = relationship("Notification", back_populates="user")

class AuthToken(Base):
    __tablename__ = "auth_tokens"
    
    token = Column(String(36), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime)
    
    user = relationship("User")

class Tambak(Base):
    __tablename__ = "tambak"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    country = Column(String(100), nullable=False)
    province = Column(String(100), nullable=False)
    city = Column(String(100), nullable=False)
    district = Column(String(100), nullable=False)
    village = Column(String(100), nullable=False)
    address = Column(String(255), nullable=False)
    cultivation_type = Column(String(100), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    
    owner = relationship("User", back_populates="tambaks")
    kolams = relationship("Kolam", back_populates="tambak")

class Device(Base):
    __tablename__ = "devices"
    
    id = Column(Integer, primary_key=True, index=True)
    uid = Column(String(36), unique=True, nullable=False)
    name = Column(String(100), nullable=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    
    # Threshold settings
    temp_min_threshold = Column(Float, nullable=True)
    temp_max_threshold = Column(Float, nullable=True)
    ph_min_threshold = Column(Float, nullable=True)
    ph_max_threshold = Column(Float, nullable=True)
    do_min_threshold = Column(Float, nullable=True)
    tds_max_threshold = Column(Float, nullable=True)
    ammonia_max_threshold = Column(Float, nullable=True)
    salinitas_min_threshold = Column(Float, nullable=True)
    salinitas_max_threshold = Column(Float, nullable=True)
    
    # Status monitoring
    last_seen = Column(DateTime)  # Timestamp terakhir komunikasi
    status = Column(String(10), default='offline')  # 'online', 'offline', 'maintenance'
    connection_interval = Column(Integer, default=5)  # Dalam menit
    
    owner = relationship("User", back_populates="devices")
    kolam = relationship("Kolam", back_populates="device", uselist=False)
    sensor_data = relationship("SensorData", back_populates="device")
    notifications = relationship("Notification", back_populates="device")

class Kolam(Base):
    __tablename__ = "kolam"
    
    id = Column(Integer, primary_key=True, index=True)
    nama = Column(String(100), nullable=False)
    tipe = Column(String(50), nullable=False)
    panjang = Column(Float)
    lebar = Column(Float)
    kedalaman = Column(Float)
    komoditas = Column(String(100))
    tambak_id = Column(Integer, ForeignKey("tambak.id"))
    device_id = Column(Integer, ForeignKey("devices.id"), unique=True)
    
    tambak = relationship("Tambak", back_populates="kolams")
    device = relationship("Device", back_populates="kolam")

class SensorData(Base):
    __tablename__ = "sensor_data"
    
    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(Integer, ForeignKey("devices.id", ondelete="CASCADE"))
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    suhu = Column(Float)
    ph = Column(Float)
    do = Column(Float)
    tds = Column(Float)
    ammonia = Column(Float)
    salinitas = Column(Float)
    
    device = relationship("Device", back_populates="sensor_data")
    
    __table_args__ = (
        Index('ix_sensor_data_device_timestamp', 'device_id', 'timestamp'),
    )

class Notification(Base):
    __tablename__ = "notifications"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    device_id = Column(Integer, ForeignKey("devices.id"))
    message = Column(String(255))
    parameter = Column(String(50))  # 'suhu', 'ph', 'do', dll
    threshold_value = Column(Float)
    current_value = Column(Float)
    is_read = Column(Boolean, default=False)
    fcm_sent = Column(Boolean, default=False)
    timestamp = Column(DateTime, default=datetime.utcnow)
    
    user = relationship("User", back_populates="notifications")
    device = relationship("Device", back_populates="notifications")

class ThresholdAlertState(Base):
    __tablename__ = "threshold_alert_states"

    device_id = Column(Integer, ForeignKey("devices.id", ondelete="CASCADE"), primary_key=True)
    parameter = Column(String(50), primary_key=True)
    threshold_type = Column(String(3), primary_key=True)
    threshold_value = Column(Float, nullable=False)
    is_active = Column(Boolean, nullable=False, default=False)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)
