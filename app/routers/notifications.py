from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from datetime import datetime, timedelta
from app import models, schemas, database
from app.auth import get_current_user
from typing import List

router = APIRouter(prefix="/notifications", tags=["Notifications"])

@router.get("/", response_model=List[schemas.NotificationResponse])
def get_user_notifications(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(database.get_db),
    days: int = Query(7, ge=1, le=365, description="Filter by last X days"),
    unread_only: bool = Query(False, description="Filter only unread notifications"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000)
):
    """
    Get user notifications with filters
    - days: Filter by last X days (default: 7)
    - unread_only: Only show unread notifications (default: False)
    - skip: Pagination offset
    - limit: Max items per page (max: 1000)
    """
    try:
        start_date = datetime.utcnow() - timedelta(days=days)

        query = db.query(models.Notification).options(
            joinedload(models.Notification.device)  # Eager loading untuk device
        ).filter(
            models.Notification.user_id == current_user.id,
            models.Notification.timestamp >= start_date
        )

        if unread_only:
            query = query.filter(models.Notification.is_read == False)

        notifications = query.order_by(
            models.Notification.timestamp.desc()
        ).offset(skip).limit(limit).all()

        # Format response sesuai schema
        return [{
            "id": notif.id,
            "device_id": notif.device_id,
            "device_name": notif.device.name
            if notif.device and notif.device.user_id == current_user.id
            else "Unknown Device",
            "message": notif.message,
            "parameter": notif.parameter,
            "threshold_value": notif.threshold_value,
            "current_value": notif.current_value,
            "is_read": notif.is_read,
            "fcm_sent": notif.fcm_sent,
            "timestamp": notif.timestamp
        } for notif in notifications]

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error fetching notifications: {str(e)}"
        )

@router.put("/{notification_id}/read", status_code=204)
def mark_notification_as_read(
    notification_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(database.get_db)
):
    """
    Mark a notification as read
    """
    notification = db.query(models.Notification).filter(
        models.Notification.id == notification_id,
        models.Notification.user_id == current_user.id
    ).first()

    if not notification:
        raise HTTPException(
            status_code=404,
            detail="Notification not found or not owned by user"
        )

    if not notification.is_read:
        notification.is_read = True
        db.commit()
    
    return None

@router.put("/read-all", status_code=204)
def mark_all_notifications_read(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(database.get_db)
):
    """
    Mark all user notifications as read
    """
    db.query(models.Notification).filter(
        models.Notification.user_id == current_user.id,
        models.Notification.is_read == False
    ).update({"is_read": True})
    db.commit()
    return None

@router.get("/unread-count", response_model=int)
def get_unread_count(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(database.get_db)
):
    """
    Get count of unread notifications
    """
    return db.query(models.Notification).filter(
        models.Notification.user_id == current_user.id,
        models.Notification.is_read == False
    ).count()
