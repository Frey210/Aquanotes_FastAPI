from fastapi import APIRouter, Depends, HTTPException, Header, Query, status
from sqlalchemy.orm import Session
from sqlalchemy import func, or_
import os
import hmac
import json
from datetime import datetime, timedelta, timezone
from app import models, schemas, database
from app.auth import require_admin
from app.device_state import operational_mode, utc_naive
from app.assignments import replace_active_assignment
from app.mqtt_provisioning import MqttProvisioningError, provision_device
from typing import List

router = APIRouter(prefix="/admin", tags=["Administrator"])

# Dapatkan API Key dari environment variable
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY")

def _valid_admin_key(received_key: str | None) -> bool:
    return bool(
        ADMIN_API_KEY
        and received_key
        and hmac.compare_digest(received_key, ADMIN_API_KEY)
    )

@router.post("/devices", response_model=schemas.DeviceResponse)
def register_device(
    device: schemas.DeviceRegister,
    db: Session = Depends(database.get_db),
    x_api_key: str = Header(None, alias="X-API-Key")
):
    if not _valid_admin_key(x_api_key):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API Key",
            headers={"WWW-Authenticate": "APIKey"}
        )
    
    # Cek apakah UID sudah terdaftar
    existing = db.query(models.Device).filter(
        models.Device.uid == device.uid
    ).first()
    
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Device UID already registered"
        )
    
    # Buat device baru tanpa pemilik
    new_device = models.Device(uid=device.uid, power_profile=device.power_profile)
    db.add(new_device)
    db.commit()
    db.refresh(new_device)
    
    return new_device

@router.get("/devices", response_model=List[schemas.AdminDeviceResponse])
def list_devices(
    db: Session = Depends(database.get_db),
    x_api_key: str = Header(None, alias="X-API-Key")
):
    if not _valid_admin_key(x_api_key):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API Key",
            headers={"WWW-Authenticate": "APIKey"}
        )
    
    # Dapatkan semua device dengan informasi user
    devices = db.query(
        models.Device.id,
        models.Device.uid,
        models.Device.name,
        models.Device.user_id,
        models.User.name.label("user_name")
    ).outerjoin(
        models.User, models.Device.user_id == models.User.id
    ).all()
    
    # Format respons
    result = []
    for device in devices:
        result.append({
            "id": device.id,
            "uid": device.uid,
            "name": device.name,
            "user_id": device.user_id,
            "user_name": device.user_name,
            "registered": device.user_id is not None
        })
    
    return result


def _connectivity_status(device: models.Device, now: datetime | None = None) -> str:
    if device.last_seen is None:
        return "never_seen"

    now = now or datetime.utcnow()
    interval = device.connection_interval or 5
    age = now - device.last_seen
    if age > timedelta(minutes=interval * 2):
        return "offline"
    if age > timedelta(minutes=interval):
        return "stale"
    return "online"


def _fleet_device(device: models.Device) -> dict:
    kolam = device.kolam
    tambak = kolam.tambak if kolam else None
    return {
        "id": device.id,
        "uid": device.uid,
        "name": device.name,
        "user_id": device.user_id,
        "user_name": device.owner.name if device.owner else None,
        "tambak_name": tambak.name if tambak else None,
        "kolam_name": kolam.nama if kolam else None,
        "connectivity_status": _connectivity_status(device),
        "operational_mode": operational_mode(device),
        "last_seen": device.last_seen,
        "connection_interval": device.connection_interval or 5,
        "deactivation_scheduled_at": device.deactivation_scheduled_at,
        "mqtt_credential_status": device.mqtt_credential_status or "unprovisioned",
        "current_firmware_version": device.current_firmware_version,
        "power_profile": device.power_profile or "portable",
    }


def _audit(
    db: Session,
    actor: models.User,
    action: str,
    device: models.Device,
    before: dict | None,
    after: dict | None,
    reason: str | None = None,
):
    db.add(models.AuditLog(
        actor_user_id=actor.id,
        action=action,
        entity_type="device",
        entity_id=str(device.id),
        before_json=json.dumps(before, default=str) if before else None,
        after_json=json.dumps(after, default=str) if after else None,
        reason=reason,
    ))


@router.get("/summary", response_model=schemas.AdminSummaryResponse)
def fleet_summary(
    _: models.User = Depends(require_admin),
    db: Session = Depends(database.get_db),
):
    devices = db.query(models.Device).all()
    counts = {status: 0 for status in ("online", "stale", "offline", "never_seen")}
    for device in devices:
        counts[_connectivity_status(device)] += 1

    return {
        "total": len(devices),
        **counts,
        "maintenance": sum(device.status == "maintenance" for device in devices),
        "inactive": sum(operational_mode(device) == "inactive" for device in devices),
        "scheduled_deactivation": sum(
            device.deactivation_scheduled_at is not None and operational_mode(device) != "inactive"
            for device in devices
        ),
        "pending_maintenance": db.query(models.MaintenanceRequest).filter(
            models.MaintenanceRequest.status.in_(("requested", "in_progress"))
        ).count(),
        "unassigned": sum(device.user_id is None for device in devices),
        "active_alerts": db.query(models.ThresholdAlertState).filter(
            models.ThresholdAlertState.is_active.is_(True)
        ).count(),
    }


@router.get("/fleet/devices", response_model=schemas.AdminFleetDevicePage)
def fleet_devices(
    search: str | None = Query(None, max_length=100),
    connectivity: str | None = Query(None, pattern="^(online|stale|offline|never_seen)$"),
    operational_mode: str | None = Query(None, pattern="^(active|maintenance|inactive)$"),
    assignment: str | None = Query(None, pattern="^(assigned|unassigned)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    _: models.User = Depends(require_admin),
    db: Session = Depends(database.get_db),
):
    query = db.query(models.Device)
    if search:
        term = f"%{search.strip()}%"
        query = query.outerjoin(models.User).filter(or_(
            models.Device.uid.ilike(term),
            models.Device.name.ilike(term),
            models.User.name.ilike(term),
        ))

    # ponytail: in-memory derived-status filtering is enough for the current fleet;
    # move connectivity derivation into SQL when fleet pagination becomes expensive.
    items = [_fleet_device(device) for device in query.order_by(models.Device.id.desc()).all()]
    if connectivity:
        items = [item for item in items if item["connectivity_status"] == connectivity]
    if operational_mode:
        items = [item for item in items if item["operational_mode"] == operational_mode]
    if assignment:
        assigned = assignment == "assigned"
        items = [item for item in items if (item["user_id"] is not None) == assigned]

    total = len(items)
    start = (page - 1) * page_size
    return {"items": items[start:start + page_size], "page": page, "page_size": page_size, "total": total}


@router.get("/users", response_model=schemas.AdminUserPage)
def admin_users(
    search: str | None = Query(None, max_length=100),
    role: str | None = Query(None, pattern="^(user|admin)$"),
    verification: str | None = Query(None, pattern="^(verified|unverified)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    _: models.User = Depends(require_admin),
    db: Session = Depends(database.get_db),
):
    query = db.query(models.User)
    if search:
        term = f"%{search.strip()}%"
        query = query.filter(or_(models.User.name.ilike(term), models.User.email.ilike(term)))
    if role:
        query = query.filter(models.User.role == role)
    if verification:
        query = query.filter(models.User.email_verified.is_(verification == "verified"))

    total = query.count()
    users = query.order_by(models.User.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    # ponytail: three small aggregate queries per user are sufficient for the current user count.
    items = [{
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "role": user.role,
        "email_verified": user.email_verified,
        "created_at": user.created_at,
        "last_login": db.query(func.max(models.AuthToken.created_at)).filter(models.AuthToken.user_id == user.id).scalar(),
        "device_count": db.query(models.Device).filter(models.Device.user_id == user.id).count(),
        "tambak_count": db.query(models.Tambak).filter(models.Tambak.user_id == user.id).count(),
    } for user in users]
    all_users = db.query(models.User).count()
    verified = db.query(models.User).filter(models.User.email_verified.is_(True)).count()
    return {
        "items": items,
        "page": page,
        "page_size": page_size,
        "total": total,
        "all_users": all_users,
        "verified": verified,
        "unverified": all_users - verified,
    }


@router.post("/fleet/devices", response_model=schemas.AdminMqttCredentialResponse, status_code=201)
def create_fleet_device(
    payload: schemas.DeviceRegister,
    actor: models.User = Depends(require_admin),
    db: Session = Depends(database.get_db),
):
    if db.query(models.Device).filter(models.Device.uid == payload.uid).first():
        raise HTTPException(status_code=409, detail="Device UID already registered")

    device = models.Device(uid=payload.uid, power_profile=payload.power_profile)
    db.add(device)
    db.flush()
    _audit(db, actor, "device.create", device, None, {"uid": device.uid, "power_profile": device.power_profile})
    db.commit()
    db.refresh(device)
    return _provision_mqtt(device, actor, db)


@router.post("/fleet/devices/{device_id}/mqtt-credential", response_model=schemas.AdminMqttCredentialResponse)
def provision_fleet_device_mqtt(
    device_id: int,
    actor: models.User = Depends(require_admin),
    db: Session = Depends(database.get_db),
):
    device = db.get(models.Device, device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    return _provision_mqtt(device, actor, db)


def _provision_mqtt(device: models.Device, actor: models.User, db: Session) -> dict:
    try:
        credential = provision_device(device.uid, device.power_profile or "portable")
    except MqttProvisioningError as exc:
        device.mqtt_credential_status = "error"
        device.mqtt_credential_updated_at = datetime.utcnow()
        _audit(db, actor, "device.mqtt.error", device, None, {"uid": device.uid})
        db.commit()
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    device.mqtt_credential_status = "ready"
    device.mqtt_credential_updated_at = datetime.utcnow()
    _audit(db, actor, "device.mqtt.provision", device, None, {"uid": device.uid, "status": "ready"})
    db.commit()
    db.refresh(device)
    return _fleet_device(device) | credential


@router.get("/fleet/devices/{device_id}", response_model=schemas.AdminFleetDeviceResponse)
def get_fleet_device(
    device_id: int,
    _: models.User = Depends(require_admin),
    db: Session = Depends(database.get_db),
):
    device = db.get(models.Device, device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    return _fleet_device(device)


@router.patch("/fleet/devices/{device_id}", response_model=schemas.AdminFleetDeviceResponse)
def update_fleet_device(
    device_id: int,
    payload: schemas.AdminDeviceUpdate,
    actor: models.User = Depends(require_admin),
    db: Session = Depends(database.get_db),
):
    device = db.get(models.Device, device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    before = _fleet_device(device)
    if payload.name is not None:
        device.name = payload.name
    if payload.connection_interval is not None:
        device.connection_interval = payload.connection_interval
    if payload.operational_mode is not None:
        if payload.operational_mode == "maintenance":
            device.status = "maintenance"
        elif payload.operational_mode == "inactive":
            device.status = "inactive"
            device.deactivation_scheduled_at = None
        else:
            device.status = "online" if _connectivity_status(device) == "online" else "offline"
            device.deactivation_scheduled_at = None
    if payload.power_profile is not None:
        device.power_profile = payload.power_profile
    if "deactivation_scheduled_at" in payload.model_fields_set:
        device.deactivation_scheduled_at = utc_naive(payload.deactivation_scheduled_at) if payload.deactivation_scheduled_at else None
        if device.deactivation_scheduled_at and device.deactivation_scheduled_at <= datetime.utcnow():
            device.status = "inactive"

    db.flush()
    after = _fleet_device(device)
    _audit(db, actor, "device.update", device, before, after, payload.reason)
    db.commit()
    db.refresh(device)
    return _fleet_device(device)


@router.post("/fleet/devices/{device_id}/unassign", response_model=schemas.AdminFleetDeviceResponse)
def unassign_fleet_device(
    device_id: int,
    actor: models.User = Depends(require_admin),
    db: Session = Depends(database.get_db),
):
    device = db.get(models.Device, device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    before = _fleet_device(device)
    if device.kolam:
        device.kolam.device_id = None
    device.user_id = None
    replace_active_assignment(db, device)
    device.name = None
    device.status = "offline"
    device.last_seen = None
    device.connection_interval = 5
    device.deactivation_scheduled_at = None
    db.flush()
    _audit(db, actor, "device.unassign", device, before, _fleet_device(device), "Penyandingan dilepas oleh admin")
    db.commit()
    db.refresh(device)
    return _fleet_device(device)


_PARAMETERS = (
    ("suhu", "Suhu", "°C", "temp_min_threshold", "temp_max_threshold"),
    ("ph", "pH", "", "ph_min_threshold", "ph_max_threshold"),
    ("do", "Oksigen terlarut", "mg/L", "do_min_threshold", None),
    ("tds", "TDS", "ppm", None, "tds_max_threshold"),
    ("ammonia", "Amonia", "mg/L", None, "ammonia_max_threshold"),
    ("salinitas", "Salinitas", "ppt", "salinitas_min_threshold", "salinitas_max_threshold"),
)


def _outside_limit(device: models.Device, parameter: str, value: float | None) -> bool:
    if value is None:
        return False
    _, _, _, min_attr, max_attr = next(item for item in _PARAMETERS if item[0] == parameter)
    minimum = getattr(device, min_attr) if min_attr else None
    maximum = getattr(device, max_attr) if max_attr else None
    return (minimum is not None and value < minimum) or (maximum is not None and value > maximum)


def _sensor_values(reading: models.SensorData | None, tambak=None) -> dict | None:
    if not reading:
        return None
    timestamp = reading.timestamp.replace(tzinfo=timezone.utc) if reading.timestamp.tzinfo is None else reading.timestamp.astimezone(timezone.utc)
    return {key: getattr(reading, key) for key, *_ in _PARAMETERS} | {
        "timestamp": timestamp
    }


@router.get("/sensors", response_model=schemas.AdminSensorOverviewResponse)
def sensor_overview(
    last_n: int = Query(24, ge=1, le=100),
    _: models.User = Depends(require_admin),
    db: Session = Depends(database.get_db),
):
    devices = db.query(models.Device).order_by(models.Device.id.desc()).all()
    summaries = {key: [] for key, *_ in _PARAMETERS}
    attention = {key: 0 for key, *_ in _PARAMETERS}
    covered = {key: 0 for key, *_ in _PARAMETERS}
    result = []
    # ponytail: one bounded query per device is adequate for the current fleet; batch when fleet size makes it measurable.
    for device in devices:
        readings = db.query(models.SensorData).filter(
            models.SensorData.device_id == device.id
        ).order_by(models.SensorData.timestamp.desc()).limit(last_n).all()
        latest = readings[0] if readings else None
        flagged = []
        if latest:
            for key, *_ in _PARAMETERS:
                value = getattr(latest, key)
                if value is not None:
                    summaries[key].append(value)
                    _, _, _, min_attr, max_attr = next(item for item in _PARAMETERS if item[0] == key)
                    if (min_attr and getattr(device, min_attr) is not None) or (max_attr and getattr(device, max_attr) is not None):
                        covered[key] += 1
                if _outside_limit(device, key, value):
                    attention[key] += 1
                    flagged.append(key)
        tambak = device.kolam.tambak if device.kolam else None
        result.append(_fleet_device(device) | {
            "latest_data": _sensor_values(latest, tambak),
            "historical_data": [_sensor_values(reading, tambak) for reading in reversed(readings)],
            "attention_parameters": flagged,
        })

    parameters = []
    for key, label, unit, *_ in _PARAMETERS:
        values = summaries[key]
        parameters.append({
            "parameter": key,
            "label": label,
            "unit": unit,
            "devices_with_data": len(values),
            "devices_with_limits": covered[key],
            "needs_attention": attention[key],
            "average": sum(values) / len(values) if values else None,
            "minimum": min(values) if values else None,
            "maximum": max(values) if values else None,
        })
    return {"generated_at": datetime.utcnow(), "parameters": parameters, "devices": result}


def _maintenance_request(item: models.MaintenanceRequest, db: Session) -> dict:
    device = db.get(models.Device, item.device_id)
    user = db.get(models.User, item.user_id)
    return {
        "id": item.id,
        "device_id": item.device_id,
        "device_name": (device.name or device.uid) if device else "Device dihapus",
        "user_name": user.name if user else "Pengguna tidak tersedia",
        "status": item.status,
        "technician_name": item.technician_name,
        "admin_note": item.admin_note,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


@router.get("/maintenance-requests", response_model=List[schemas.MaintenanceRequestResponse])
def maintenance_requests(
    active_only: bool = True,
    _: models.User = Depends(require_admin),
    db: Session = Depends(database.get_db),
):
    query = db.query(models.MaintenanceRequest)
    if active_only:
        query = query.filter(models.MaintenanceRequest.status.in_(("requested", "in_progress")))
    return [_maintenance_request(item, db) for item in query.order_by(models.MaintenanceRequest.created_at.desc()).all()]


@router.patch("/maintenance-requests/{request_id}", response_model=schemas.MaintenanceRequestResponse)
def update_maintenance_request(
    request_id: int,
    payload: schemas.MaintenanceRequestUpdate,
    actor: models.User = Depends(require_admin),
    db: Session = Depends(database.get_db),
):
    item = db.get(models.MaintenanceRequest, request_id)
    if not item:
        raise HTTPException(status_code=404, detail="Maintenance request not found")
    item.status = payload.status
    if payload.technician_name is not None:
        item.technician_name = payload.technician_name
    if payload.admin_note is not None:
        item.admin_note = payload.admin_note
    device = db.get(models.Device, item.device_id)
    if device:
        _audit(db, actor, "maintenance.update", device, None, {"request_id": item.id, "status": item.status}, payload.admin_note)
    db.commit()
    db.refresh(item)
    return _maintenance_request(item, db)
