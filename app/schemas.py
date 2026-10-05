from pydantic import BaseModel, EmailStr, ConfigDict, Field, validator
from typing import Any, Optional, List, Union, Literal
from datetime import datetime, date

class UserCreate(BaseModel):
    name: str
    email: EmailStr
    password: str

class UserLogin(BaseModel):
    email: EmailStr
    password: str


class EmailRequest(BaseModel):
    email: EmailStr


class EmailTokenConfirm(BaseModel):
    token: str = Field(..., min_length=32)


class PasswordResetConfirm(EmailTokenConfirm):
    password: str = Field(..., min_length=8, max_length=128)


class MessageResponse(BaseModel):
    message: str

class UserResponse(BaseModel):
    id: int
    name: str
    email: EmailStr
    
    model_config = ConfigDict(from_attributes=True)

class Token(BaseModel):
    access_token: str
    token_type: str


class UserSessionResponse(BaseModel):
    id: int
    name: str
    email: EmailStr
    role: Literal["user", "admin"]

    model_config = ConfigDict(from_attributes=True)

class DeviceRegister(BaseModel):
    uid: str
    power_profile: Literal["portable", "panel"] = "portable"

class DeviceCreate(BaseModel):
    uid: str
    name: str

class DeviceResponse(BaseModel):
    id: int
    uid: str
    name: Optional[str] = None
    user_id: Optional[int] = None
    status: Optional[str] = None
    last_seen: Optional[datetime] = None
    connection_interval: Optional[int] = None
    
    model_config = ConfigDict(from_attributes=True)

class DeviceStatusResponse(BaseModel):
    online: int
    offline: int
    maintenance: int
    devices: List[DeviceResponse]

class TambakCreate(BaseModel):
    name: str
    country: str
    province: str
    city: str
    district: str
    village: str
    address: str
    cultivation_type: str

class TambakResponse(BaseModel):
    id: int
    name: str
    country: str
    province: str
    city: str
    district: str
    village: str
    address: str
    cultivation_type: str

    class Config:
        from_attributes = True

class KolamCreate(BaseModel):
    nama: str
    tipe: str
    panjang: float
    lebar: float
    kedalaman: float
    komoditas: str
    tambak_id: int
    device_id: int

class KolamResponse(BaseModel):
    id: int
    nama: str
    komoditas: str
    
    model_config = ConfigDict(from_attributes=True)

class SensorDataCreate(BaseModel):
    uid: str
    suhu: Optional[float] = None
    ph: Optional[float] = None
    do: Optional[float] = None
    tds: Optional[float] = None
    ammonia: Optional[float] = None
    salinitas: Optional[float] = None
    timestamp: Any = Field(None, description="Field legacy opsional; waktu sensor ditetapkan oleh server")

class SensorDataResponse(BaseModel):
    id: int
    device_id: int
    timestamp: datetime
    suhu: Optional[float] = None
    ph: Optional[float] = None
    do: Optional[float] = None
    tds: Optional[float] = None
    ammonia: Optional[float] = None
    salinitas: Optional[float] = None
    
    class Config:
        from_attributes = True

class SensorDataSummary(BaseModel):
    suhu: Optional[float] = None
    ph: Optional[float] = None
    do: Optional[float] = None
    tds: Optional[float] = None
    ammonia: Optional[float] = None
    salinitas: Optional[float] = None
    timestamp: Optional[datetime] = None

class DeviceMonitoring(BaseModel):
    id: int
    name: str
    latest_data: Optional[SensorDataSummary] = None  # Perubahan disini
    historical_data: list[SensorDataSummary] = []

class KolamMonitoring(BaseModel):
    id: int
    nama: str
    devices: list[DeviceMonitoring]

class MonitoringResponse(BaseModel):
    kolam_list: list[KolamMonitoring]
    current_kolam_id: Optional[int] = None
    current_device_id: Optional[int] = None

class AdminDeviceResponse(BaseModel):
    id: int
    uid: str
    name: Optional[str] = None
    user_id: Optional[int] = None
    user_name: Optional[str] = None
    registered: bool
    
    model_config = ConfigDict(from_attributes=True)


class AdminSummaryResponse(BaseModel):
    total: int
    online: int
    stale: int
    offline: int
    never_seen: int
    maintenance: int
    inactive: int
    scheduled_deactivation: int
    pending_maintenance: int
    unassigned: int
    active_alerts: int


class AdminFleetDeviceResponse(BaseModel):
    id: int
    uid: str
    name: Optional[str] = None
    user_id: Optional[int] = None
    user_name: Optional[str] = None
    tambak_name: Optional[str] = None
    kolam_name: Optional[str] = None
    connectivity_status: Literal["online", "stale", "offline", "never_seen"]
    operational_mode: Literal["active", "maintenance", "inactive"]
    last_seen: Optional[datetime] = None
    connection_interval: int
    deactivation_scheduled_at: Optional[datetime] = None
    mqtt_credential_status: Literal["unprovisioned", "ready", "active", "error"]
    current_firmware_version: Optional[str] = None
    power_profile: Literal["portable", "panel"]


class AdminMqttCredentialResponse(AdminFleetDeviceResponse):
    mqtt_password: str
    secrets_h: str


OtaReleaseStatus = Literal["draft", "ready", "retired"]
OtaAssignmentState = Literal[
    "assigned", "deferred", "downloading", "downloaded", "rebooting",
    "pending_verify", "success", "failed", "rolled_back", "cancelled",
]


class FirmwareReleaseCreate(BaseModel):
    version: str = Field(..., min_length=5, max_length=64)
    release_notes: Optional[str] = Field(None, max_length=5000)


class FirmwareReleaseResponse(BaseModel):
    id: int
    version: str
    status: OtaReleaseStatus
    sha256: str
    size_bytes: int
    signing_key_id: Optional[str] = None
    release_notes: Optional[str] = None
    created_by: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class OtaAssignmentCreate(BaseModel):
    release_id: int = Field(..., gt=0)
    device_ids: List[int] = Field(..., min_length=1, max_length=100)
    mandatory: bool = False
    rollback: bool = False


class OtaAssignmentResponse(BaseModel):
    id: int
    device_id: int
    device_uid: str
    release_id: int
    version: str
    from_version: Optional[str] = None
    state: OtaAssignmentState
    progress: Optional[int] = None
    attempt_count: int
    last_error_code: Optional[str] = None
    last_error_detail: Optional[str] = None
    requested_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    last_report_at: Optional[datetime] = None
    is_rollback: bool
    mandatory: bool


class OtaAssignmentBatchResponse(BaseModel):
    items: List[OtaAssignmentResponse]
    publish_failures: List[int] = Field(default_factory=list)


class OtaStatusMessage(BaseModel):
    schema_version: int = Field(1, alias="schema")
    message_id: str = Field(..., min_length=1, max_length=128)
    assignment_id: int = Field(..., gt=0)
    running_version: str = Field(..., min_length=1, max_length=64)
    target_version: str = Field(..., min_length=1, max_length=64)
    state: OtaAssignmentState
    progress: Optional[int] = Field(None, ge=0, le=100)
    error_code: Optional[str] = Field(None, max_length=64)
    error_detail: Optional[str] = Field(None, max_length=500)

    model_config = ConfigDict(populate_by_name=True)


class AdminFleetDevicePage(BaseModel):
    items: List[AdminFleetDeviceResponse]
    page: int
    page_size: int
    total: int


class AdminUserResponse(BaseModel):
    id: int
    name: str
    email: EmailStr
    role: Literal["user", "admin"]
    email_verified: bool
    created_at: datetime
    last_login: Optional[datetime] = None
    device_count: int
    tambak_count: int


class AdminUserPage(BaseModel):
    items: List[AdminUserResponse]
    page: int
    page_size: int
    total: int
    all_users: int
    verified: int
    unverified: int


class AdminDeviceUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    connection_interval: Optional[int] = Field(None, ge=1, le=60)
    operational_mode: Optional[Literal["active", "maintenance", "inactive"]] = None
    power_profile: Optional[Literal["portable", "panel"]] = None
    deactivation_scheduled_at: Optional[datetime] = None
    reason: Optional[str] = Field(None, max_length=255)


class AdminParameterSummary(BaseModel):
    parameter: Literal["suhu", "ph", "do", "tds", "ammonia", "salinitas"]
    label: str
    unit: str
    devices_with_data: int
    devices_with_limits: int
    needs_attention: int
    average: Optional[float] = None
    minimum: Optional[float] = None
    maximum: Optional[float] = None


class AdminSensorDeviceResponse(AdminFleetDeviceResponse):
    latest_data: Optional[SensorDataSummary] = None
    historical_data: List[SensorDataSummary] = []
    attention_parameters: List[str] = []


class AdminSensorOverviewResponse(BaseModel):
    generated_at: datetime
    parameters: List[AdminParameterSummary]
    devices: List[AdminSensorDeviceResponse]


class MaintenanceRequestResponse(BaseModel):
    id: int
    device_id: int
    device_name: str
    user_name: str
    status: Literal["requested", "in_progress", "completed", "cancelled"]
    technician_name: Optional[str] = None
    admin_note: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class MaintenanceRequestUpdate(BaseModel):
    status: Literal["in_progress", "completed", "cancelled"]
    technician_name: Optional[str] = Field(None, max_length=100)
    admin_note: Optional[str] = Field(None, max_length=255)

class ThresholdSettings(BaseModel):
    temp_min: Optional[float] = Field(None, ge=0, description="Minimum temperature threshold in °C")
    temp_max: Optional[float] = Field(None, ge=0, description="Maximum temperature threshold in °C")
    ph_min: Optional[float] = Field(None, ge=0, le=14, description="Minimum pH threshold")
    ph_max: Optional[float] = Field(None, ge=0, le=14, description="Maximum pH threshold")
    do_min: Optional[float] = Field(None, ge=0, description="Minimum dissolved oxygen threshold in mg/L")
    tds_max: Optional[float] = Field(None, ge=0, description="Maximum TDS threshold in ppm")
    ammonia_max: Optional[float] = Field(None, ge=0, description="Maximum ammonia threshold in mg/L")
    salinitas_min: Optional[float] = Field(None, ge=0, description="Minimum salinity threshold in ppt")
    salinitas_max: Optional[float] = Field(None, ge=0, description="Maximum salinity threshold in ppt")

class DeviceThresholdResponse(ThresholdSettings):
    device_id: int
    device_name: str

class NotificationResponse(BaseModel):
    id: int
    device_id: int
    device_name: str
    message: str
    parameter: str
    threshold_value: float
    current_value: float
    is_read: bool
    timestamp: datetime
    fcm_sent: bool = Field(False, description="Status pengiriman FCM")

    class Config:
        from_attributes = True

class FCMTokenUpdate(BaseModel):
    token: str = Field(..., min_length=10, description="FCM token dari perangkat")

class UserProfileUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=100, description="Nama baru")
    old_password: Optional[str] = Field(None, min_length=6, description="Password saat ini")
    new_password: Optional[str] = Field(None, min_length=6, description="Password baru")
    
    # Validasi: Jika ingin ganti password, harus sertakan old_password
    @validator('new_password')
    def check_old_password(cls, v, values):
        if v and 'old_password' not in values:
            raise ValueError("Old password is required when changing password")
        return v

# Tambahkan field fcm_token di UserResponse jika belum ada
class UserResponse(BaseModel):
    id: int
    name: str
    email: EmailStr
    created_at: datetime
    fcm_token: Optional[str] = None  # Tambahkan ini jika belum ada
    
    class Config:
        from_attributes = True

class ExportRequest(BaseModel):
    device_id: int
    start_date: date
    end_date: date

class DeviceUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    connection_interval: Optional[int] = Field(None, ge=1, le=60)

class TambakUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    country: Optional[str] = Field(None, min_length=1, max_length=100)
    province: Optional[str] = Field(None, min_length=1, max_length=100)
    city: Optional[str] = Field(None, min_length=1, max_length=100)
    district: Optional[str] = Field(None, min_length=1, max_length=100)
    village: Optional[str] = Field(None, min_length=1, max_length=100)
    address: Optional[str] = Field(None, min_length=1, max_length=255)
    cultivation_type: Optional[str] = Field(None, min_length=1, max_length=100)

class KolamUpdate(BaseModel):
    nama: Optional[str] = Field(None, min_length=1, max_length=100)
    tipe: Optional[str] = Field(None, min_length=1, max_length=50)
    panjang: Optional[float] = Field(None, gt=0)
    lebar: Optional[float] = Field(None, gt=0)
    kedalaman: Optional[float] = Field(None, gt=0)
    komoditas: Optional[str] = Field(None, min_length=1, max_length=100)
    tambak_id: Optional[int] = Field(None, gt=0)
    device_id: Optional[int] = Field(None, gt=0)

class MoveDeviceRequest(BaseModel):
    target_kolam_id: int = Field(..., gt=0, description="ID kolam tujuan")
