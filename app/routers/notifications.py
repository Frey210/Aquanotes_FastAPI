from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app import models, schemas, database, auth
from datetime import datetime, timedelta
from typing import List
from app.firebase_service import send_fcm_notification  # Baru

router = APIRouter(prefix="/notifications", tags=["Notifications"])

@router.get("/", response_model=List[schemas.NotificationResponse])
def get_notifications(
    days: int = 7,
    unread_only: bool = False,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    query = db.query(models.Notification).filter(
        models.Notification.user_id == current_user.id,
        models.Notification.timestamp >= datetime.utcnow() - timedelta(days=days)
    )
    
    if unread_only:
        query = query.filter(models.Notification.is_read == False)
    
    notifications = query.order_by(models.Notification.timestamp.desc()).all()
    return notifications

@router.post("/{notification_id}/read", status_code=status.HTTP_200_OK)
def mark_notification_as_read(
    notification_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    notification = db.query(models.Notification).filter(
        models.Notification.id == notification_id,
        models.Notification.user_id == current_user.id
    ).first()
    
    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")
    
    notification.is_read = True
    db.commit()
    return {"message": "Notification marked as read"}

@router.post("/test-fcm", status_code=status.HTTP_200_OK)
def test_fcm_notification(
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    """
    Endpoint untuk mengirim notifikasi test ke perangkat user
    """
    if not current_user.fcm_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User doesn't have FCM token"
        )
    
    success = send_fcm_notification(
        current_user.fcm_token,
        title="Test Notifikasi",
        body="Ini adalah notifikasi test dari server",
        data={"type": "test"}
    )
    
    return {"success": success, "message": "Test notification sent"}