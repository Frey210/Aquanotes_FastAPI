from sqlalchemy import Column, Integer, String, Float, ForeignKey, DateTime, Boolean, Index, Text, UniqueConstraint, text
from sqlalchemy.orm import relationship
from datetime import datetime
from app.database import Base

class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    email = Column(String(100), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(20), nullable=False, default="user", server_default="user")
    email_verified = Column(Boolean, nullable=False, default=True, server_default=text("true"))
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


class EmailToken(Base):
    __tablename__ = "email_tokens"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash = Column(String(64), unique=True, nullable=False, index=True)
    purpose = Column(String(20), nullable=False)
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

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
    status = Column(String(20), default='offline')  # online, offline, maintenance, inactive
    connection_interval = Column(Integer, default=5)  # Dalam menit
    deactivation_scheduled_at = Column(DateTime, nullable=True)
    mqtt_credential_status = Column(String(20), nullable=False, default="unprovisioned", server_default="unprovisioned")
    mqtt_credential_updated_at = Column(DateTime, nullable=True)
    power_profile = Column(String(20), nullable=False, default="portable", server_default="portable")
    
    owner = relationship("User", back_populates="devices")
    kolam = relationship("Kolam", back_populates="device", uselist=False)
    sensor_data = relationship("SensorData", back_populates="device")
    assignments = relationship("DeviceAssignment", back_populates="device")
    notifications = relationship("Notification", back_populates="device")
    ota_assignments = relationship("DeviceOtaAssignment", back_populates="device")
    current_firmware_version = Column(String(64), nullable=True)

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
    assignment_id = Column(Integer, ForeignKey("device_assignments.id"), nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    suhu = Column(Float)
    ph = Column(Float)
    do = Column(Float)
    tds = Column(Float)
    ammonia = Column(Float)
    salinitas = Column(Float)
    
    device = relationship("Device", back_populates="sensor_data")
    assignment = relationship("DeviceAssignment", back_populates="sensor_data")
    
    __table_args__ = (
        Index('ix_sensor_data_device_timestamp', 'device_id', 'timestamp'),
        Index('ix_sensor_data_assignment_timestamp', 'assignment_id', 'timestamp'),
    )

class DeviceAssignment(Base):
    __tablename__ = "device_assignments"

    id = Column(Integer, primary_key=True)
    device_id = Column(Integer, ForeignKey("devices.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    # Snapshot IDs intentionally survive physical deletion of a pond/farm.
    kolam_id = Column(Integer, nullable=True)
    tambak_id = Column(Integer, nullable=True)
    started_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    ended_at = Column(DateTime, nullable=True)
    is_legacy = Column(Boolean, nullable=False, default=False)

    device = relationship("Device", back_populates="assignments")
    sensor_data = relationship("SensorData", back_populates="assignment")

    __table_args__ = (
        Index('ix_device_assignments_user_device', 'user_id', 'device_id'),
        Index(
            'ux_device_assignments_active',
            'device_id',
            unique=True,
            sqlite_where=text('ended_at IS NULL'),
            postgresql_where=text('ended_at IS NULL'),
        ),
    )


class MqttIngestReceipt(Base):
    __tablename__ = "mqtt_ingest_receipts"

    id = Column(Integer, primary_key=True)
    device_id = Column(Integer, ForeignKey("devices.id", ondelete="CASCADE"), nullable=False)
    message_id = Column(String(128), nullable=False)
    sensor_data_id = Column(Integer, ForeignKey("sensor_data.id", ondelete="CASCADE"), nullable=True)
    received_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    sensor_data = relationship("SensorData")

    __table_args__ = (
        UniqueConstraint("device_id", "message_id", name="uq_mqtt_receipt_device_message"),
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


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True)
    actor_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    action = Column(String(100), nullable=False)
    entity_type = Column(String(50), nullable=False)
    entity_id = Column(String(100), nullable=False)
    before_json = Column(Text, nullable=True)
    after_json = Column(Text, nullable=True)
    reason = Column(String(255), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)


class MaintenanceRequest(Base):
    __tablename__ = "maintenance_requests"

    id = Column(Integer, primary_key=True)
    device_id = Column(Integer, ForeignKey("devices.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    status = Column(String(20), nullable=False, default="requested")
    technician_name = Column(String(100), nullable=True)
    admin_note = Column(String(255), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class FirmwareRelease(Base):
    __tablename__ = "firmware_releases"

    id = Column(Integer, primary_key=True)
    version = Column(String(64), unique=True, nullable=False, index=True)
    status = Column(String(20), nullable=False, default="draft", server_default="draft")
    artifact_filename = Column(String(255), unique=True, nullable=False)
    sha256 = Column(String(64), nullable=False)
    size_bytes = Column(Integer, nullable=False)
    signature = Column(Text, nullable=True)
    signing_key_id = Column(String(32), nullable=True)
    factory_artifact_filename = Column(String(255), unique=True, nullable=True)
    factory_sha256 = Column(String(64), nullable=True)
    factory_size_bytes = Column(Integer, nullable=True)
    factory_signature = Column(Text, nullable=True)
    factory_only = Column(Boolean, nullable=False, default=False, server_default=text("false"))
    release_notes = Column(Text, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    assignments = relationship("DeviceOtaAssignment", back_populates="release")


class DeviceOtaAssignment(Base):
    __tablename__ = "device_ota_assignments"

    id = Column(Integer, primary_key=True)
    device_id = Column(Integer, ForeignKey("devices.id", ondelete="CASCADE"), nullable=False, index=True)
    release_id = Column(Integer, ForeignKey("firmware_releases.id"), nullable=False, index=True)
    from_version = Column(String(64), nullable=True)
    state = Column(String(30), nullable=False, default="assigned", server_default="assigned", index=True)
    progress = Column(Integer, nullable=True)
    attempt_count = Column(Integer, nullable=False, default=0, server_default="0")
    download_token_hash = Column(String(64), nullable=False)
    last_error_code = Column(String(64), nullable=True)
    last_error_detail = Column(String(500), nullable=True)
    requested_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    requested_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    last_report_at = Column(DateTime, nullable=True)
    is_rollback = Column(Boolean, nullable=False, default=False, server_default=text("false"))
    mandatory = Column(Boolean, nullable=False, default=False, server_default=text("false"))

    device = relationship("Device", back_populates="ota_assignments")
    release = relationship("FirmwareRelease", back_populates="assignments")
    events = relationship("DeviceOtaEvent", back_populates="assignment", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_device_ota_assignments_device_state", "device_id", "state"),
        Index(
            "ux_device_ota_assignments_active",
            "device_id",
            unique=True,
            sqlite_where=text("state IN ('assigned','deferred','downloading','downloaded','rebooting','pending_verify')"),
            postgresql_where=text("state IN ('assigned','deferred','downloading','downloaded','rebooting','pending_verify')"),
        ),
    )


class DeviceOtaEvent(Base):
    __tablename__ = "device_ota_events"

    id = Column(Integer, primary_key=True)
    assignment_id = Column(Integer, ForeignKey("device_ota_assignments.id", ondelete="CASCADE"), nullable=False)
    message_id = Column(String(128), nullable=False)
    state = Column(String(30), nullable=False)
    progress = Column(Integer, nullable=True)
    error_code = Column(String(64), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)

    assignment = relationship("DeviceOtaAssignment", back_populates="events")

    __table_args__ = (
        UniqueConstraint("assignment_id", "message_id", name="uq_device_ota_event_message"),
    )
