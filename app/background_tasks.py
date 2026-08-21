import time
import threading
import logging
from datetime import datetime, timedelta  # PERBAIKAN: Tambahkan import datetime
from sqlalchemy import or_, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session
from app import models
from app.database import SessionLocal
from app.firebase_service import send_fcm_notification
from app.assignments import get_active_assignment

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

THRESHOLD_FIELDS = (
    ('suhu', 'min', 'temp_min_threshold'),
    ('suhu', 'max', 'temp_max_threshold'),
    ('ph', 'min', 'ph_min_threshold'),
    ('ph', 'max', 'ph_max_threshold'),
    ('do', 'min', 'do_min_threshold'),
    ('tds', 'max', 'tds_max_threshold'),
    ('ammonia', 'max', 'ammonia_max_threshold'),
    ('salinitas', 'min', 'salinitas_min_threshold'),
    ('salinitas', 'max', 'salinitas_max_threshold'),
)

def _is_threshold_breached(current_value, threshold_type, threshold):
    return (threshold_type == 'min' and current_value < threshold) or \
           (threshold_type == 'max' and current_value > threshold)

def _claim_threshold_alert(db, device_id, parameter, threshold_type, threshold, breached):
    """Return True exactly once when an alert changes from inactive to active."""
    now = datetime.utcnow()
    db.execute(
        sqlite_insert(models.ThresholdAlertState).values(
            device_id=device_id,
            parameter=parameter,
            threshold_type=threshold_type,
            threshold_value=threshold,
            is_active=False,
            updated_at=now,
        ).on_conflict_do_nothing(
            index_elements=['device_id', 'parameter', 'threshold_type']
        )
    )

    state = models.ThresholdAlertState
    key = (
        (state.device_id == device_id) &
        (state.parameter == parameter) &
        (state.threshold_type == threshold_type)
    )

    if not breached:
        db.execute(
            update(state).where(key).values(
                is_active=False,
                threshold_value=threshold,
                updated_at=now,
            )
        )
        return False

    result = db.execute(
        update(state).where(key).where(
            or_(state.is_active.is_(False), state.threshold_value != threshold)
        ).values(
            is_active=True,
            threshold_value=threshold,
            updated_at=now,
        )
    )
    return result.rowcount == 1

def _seed_threshold_alert_states(db):
    """Treat conditions present before this deployment as the initial baseline."""
    devices = db.query(models.Device).filter(models.Device.user_id.isnot(None)).all()
    now = datetime.utcnow()

    for device in devices:
        assignment = get_active_assignment(db, device.id)
        if not assignment:
            continue
        latest = db.query(models.SensorData).filter(
            models.SensorData.assignment_id == assignment.id
        ).order_by(models.SensorData.timestamp.desc()).first()
        if not latest:
            continue

        for parameter, threshold_type, field_name in THRESHOLD_FIELDS:
            threshold = getattr(device, field_name)
            current_value = getattr(latest, parameter)
            if threshold is None or current_value is None:
                continue

            db.execute(
                sqlite_insert(models.ThresholdAlertState).values(
                    device_id=device.id,
                    parameter=parameter,
                    threshold_type=threshold_type,
                    threshold_value=threshold,
                    is_active=_is_threshold_breached(current_value, threshold_type, threshold),
                    updated_at=now,
                ).on_conflict_do_nothing(
                    index_elements=['device_id', 'parameter', 'threshold_type']
                )
            )

    db.commit()

def check_thresholds():
    logger.info("Starting background threshold checker")
    db = SessionLocal()
    try:
        _seed_threshold_alert_states(db)
    finally:
        db.close()

    while True:
        try:
            db = SessionLocal()
            devices = db.query(models.Device).filter(
                models.Device.user_id.isnot(None)
            ).all()
            
            for device in devices:
                assignment = get_active_assignment(db, device.id)
                if not assignment:
                    continue
                latest = db.query(models.SensorData).filter(
                    models.SensorData.assignment_id == assignment.id
                ).order_by(models.SensorData.timestamp.desc()).first()
                
                if not latest:
                    continue
                
                for param, type_, field_name in THRESHOLD_FIELDS:
                    threshold = getattr(device, field_name)
                    if threshold is None:
                        continue
                    
                    current_value = getattr(latest, param)
                    if current_value is None:
                        continue
                    
                    breached = _is_threshold_breached(current_value, type_, threshold)
                    if _claim_threshold_alert(
                        db, device.id, param, type_, threshold, breached
                    ):
                        
                        message = f"Nilai {param} {current_value} {'di bawah' if type_ == 'min' else 'di atas'} threshold {threshold}"
                        notification = models.Notification(
                            user_id=device.user_id,
                            device_id=device.id,
                            message=message,
                            parameter=param,
                            threshold_value=threshold,
                            current_value=current_value
                        )
                        db.add(notification)
                        db.flush()
                        
                        user = db.query(models.User).get(device.user_id)
                        fcm_sent = False
                        if user and user.fcm_token:
                            fcm_sent = send_fcm_notification(
                                user.fcm_token,
                                title="Peringatan Sensor",
                                body=message,
                                data={
                                    "notification_id": str(notification.id),
                                    "type": "sensor_alert",
                                    "parameter": param
                                }
                            )
                        
                        notification.fcm_sent = fcm_sent
                        logger.info(f"Notification created: {message}")

            db.commit()
            db.close()
            time.sleep(60)
            
        except Exception as e:
            logger.error(f"Error in threshold check: {str(e)}")
            try:
                if db:
                    db.rollback()
                    db.close()
            except:
                pass
            time.sleep(10)

def check_device_status():
    logger.info("Starting background device status checker")
    while True:
        try:
            db = SessionLocal()
            now = datetime.utcnow()
            
            devices = db.query(models.Device).all()
            for device in devices:
                if device.status == 'maintenance':
                    continue
                
                # PERBAIKAN: Handle None untuk last_seen
                last_seen = device.last_seen or datetime.min
                
                # Hitung threshold dinamis
                threshold_minutes = device.connection_interval * 2
                threshold = now - timedelta(minutes=threshold_minutes)
                
                if last_seen < threshold:
                    if device.status != 'offline':
                        old_status = device.status
                        device.status = 'offline'
                        db.add(device)
                        
                        if device.user_id:
                            user = db.query(models.User).get(device.user_id)
                            if user and user.fcm_token:
                                send_fcm_notification(
                                    user.fcm_token,
                                    title="Device Status Changed",
                                    body=f"Device {device.name or device.uid} is offline",
                                    data={
                                        "device_id": str(device.id),
                                        "old_status": old_status,
                                        "new_status": "offline"
                                    }
                                )
                        logger.info(f"Device {device.id} marked as offline")
                else:
                    if device.status != 'online':
                        old_status = device.status
                        device.status = 'online'
                        db.add(device)
                        
                        if device.user_id:
                            user = db.query(models.User).get(device.user_id)
                            if user and user.fcm_token:
                                send_fcm_notification(
                                    user.fcm_token,
                                    title="Device Status Changed",
                                    body=f"Device {device.name or device.uid} is back online",
                                    data={
                                        "device_id": str(device.id),
                                        "old_status": old_status,
                                        "new_status": "online"
                                    }
                                )
                        logger.info(f"Device {device.id} marked as online")
            
            db.commit()
            db.close()
            time.sleep(60)
            
        except Exception as e:
            logger.error(f"Error in device status check: {str(e)}")
            try:
                if db:
                    db.rollback()
                    db.close()
            except:
                pass
            time.sleep(10)

def start_background_task():
    thread_threshold = threading.Thread(target=check_thresholds, daemon=True)
    thread_threshold.start()
    
    thread_status = threading.Thread(target=check_device_status, daemon=True)
    thread_status.start()
    
    logger.info("All background tasks started")
