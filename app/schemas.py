from pydantic import BaseModel, EmailStr, ConfigDict, Field, validator
from typing import Optional, List, Union
from datetime import datetime, date

class UserCreate(BaseModel):
    name: str
    email: EmailStr
    password: str

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class UserResponse(BaseModel):
    id: int
    name: str
    email: EmailStr
    
    model_config = ConfigDict(from_attributes=True)

class Token(BaseModel):
    access_token: str
    token_type: str

class DeviceRegister(BaseModel):
    uid: str

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
    suhu: float
    ph: float
    do: float
    tds: float
    ammonia: float
    salinitas: float
    timestamp: str = Field(..., description="Timestamp dalam format ISO 8601 dari device (contoh: 2025-07-18T06:00:00+08:00)")

class SensorDataResponse(BaseModel):
    id: int
    device_id: int
    timestamp: datetime
    suhu: float
    ph: float
    do: float
    tds: float
    ammonia: float
    salinitas: float
    
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
