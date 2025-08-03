import time
import threading
import logging
from datetime import datetime, timedelta  # PERBAIKAN: Tambahkan import datetime
from sqlalchemy.orm import Session
from app import models
from app.database import SessionLocal
from app.firebase_service import send_fcm_notification

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def check_thresholds():
    logger.info("Starting background threshold checker")
    while True:
        try:
            db = SessionLocal()
            devices = db.query(models.Device).filter(
                models.Device.user_id.isnot(None)
            ).all()
            
            for device in devices:
                latest = db.query(models.SensorData).filter(
                    models.SensorData.device_id == device.id
                ).order_by(models.SensorData.timestamp.desc()).first()
                
                if not latest:
                    continue
                
                thresholds = [
                    ('suhu', 'min', device.temp_min_threshold),
                    ('suhu', 'max', device.temp_max_threshold),
                    ('ph', 'min', device.ph_min_threshold),
                    ('ph', 'max', device.ph_max_threshold),
                    ('do', 'min', device.do_min_threshold),
                    ('tds', 'max', device.tds_max_threshold),
                    ('ammonia', 'max', device.ammonia_max_threshold),
                    ('salinitas', 'min', device.salinitas_min_threshold),
                    ('salinitas', 'max', device.salinitas_max_threshold)
                ]
                
                for param, type_, threshold in thresholds:
                    if threshold is None:
                        continue
                    
                    current_value = getattr(latest, param)
                    if current_value is None:
                        continue
                    
                    if (type_ == 'min' and current_value < threshold) or \
                       (type_ == 'max' and current_value > threshold):
                        
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
                        db.commit()
                        logger.info(f"Notification created: {message}")
            
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