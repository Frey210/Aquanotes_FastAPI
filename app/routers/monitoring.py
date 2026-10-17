from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from datetime import datetime, timedelta, timezone
from typing import Optional, Literal
from sqlalchemy import or_, and_
import logging
from app import models, schemas, database, auth
from app.assignments import get_active_assignment

router = APIRouter(prefix="/monitoring", tags=["Monitoring"])
logger = logging.getLogger(__name__)

@router.get("/devices/{device_id}/history", response_model=schemas.SensorHistoryResponse)
def get_parameter_history(
    device_id: int,
    parameter: Literal["suhu", "ph", "do", "tds", "ammonia", "salinitas"],
    limit: int = Query(24, ge=1, le=100),
    before_id: Optional[int] = Query(None, gt=0),
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    device = db.get(models.Device, device_id)
    is_admin = current_user.role == "admin"
    if not device or (not is_admin and device.user_id != current_user.id):
        raise HTTPException(status_code=404, detail="Device not found")
    query = db.query(models.SensorData).filter(models.SensorData.device_id == device_id)
    if not is_admin:
        query = query.join(models.DeviceAssignment).filter(models.DeviceAssignment.user_id == current_user.id)

    def older_than(row):
        return or_(models.SensorData.timestamp < row.timestamp, and_(
            models.SensorData.timestamp == row.timestamp, models.SensorData.id < row.id))

    if before_id is not None:
        cursor = query.filter(models.SensorData.id == before_id).first()
        if not cursor:
            raise HTTPException(status_code=404, detail="History cursor not found")
        query = query.filter(older_than(cursor))
    column = getattr(models.SensorData, parameter)
    ordered = query.order_by(models.SensorData.timestamp.desc(), models.SensorData.id.desc())
    anchor = ordered.filter(column.is_not(None)).first()
    if not anchor:
        return {"readings": [], "next_before_id": None}
    # Keep null gaps within the historical window; never substitute old data for the live reading.
    rows = ordered.filter(or_(older_than(anchor), models.SensorData.id == anchor.id)).limit(limit).all()
    has_older = query.filter(older_than(rows[-1]), column.is_not(None)).first() is not None
    return {
        "readings": [schemas.SensorDataSummary(
            **{key: getattr(row, key) for key in ("suhu", "ph", "do", "tds", "ammonia", "salinitas")},
            timestamp=row.timestamp.replace(tzinfo=timezone.utc),
        ) for row in reversed(rows)],
        "next_before_id": rows[-1].id if has_older else None,
    }

@router.get("", response_model=schemas.MonitoringResponse, include_in_schema=False)
@router.get("/", response_model=schemas.MonitoringResponse)
def get_monitoring(
    last_n: Optional[int] = Query(
        default=10,
        description="Jumlah data sensor terakhir yang ingin diambil (default 10)",
        gt=0
    ),
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    try:
        kolams = db.query(models.Kolam).join(models.Tambak).filter(
            models.Tambak.user_id == current_user.id
        ).options(
            joinedload(models.Kolam.device)
        ).all()

        if not kolams:
            return schemas.MonitoringResponse(kolam_list=[])

        response = []
        devices = []

        for kolam in kolams:
            device_data = []
            
            if kolam.device:
                device = kolam.device
                devices.append(device)
                assignment = get_active_assignment(db, device.id)

                latest = None
                historical = []
                if assignment:
                    latest = db.query(models.SensorData).filter(
                        models.SensorData.assignment_id == assignment.id
                    ).order_by(models.SensorData.timestamp.desc()).first()

                    historical = db.query(models.SensorData).filter(
                        models.SensorData.assignment_id == assignment.id
                    ).order_by(models.SensorData.timestamp.desc()).limit(last_n).all()
                    historical.reverse()
                
                # Format latest data (handle None)
                latest_summary = None
                if latest:
                    latest_summary = schemas.SensorDataSummary(
                        suhu=latest.suhu,
                        ph=latest.ph,
                        do=latest.do,
                        tds=latest.tds,
                        ammonia=latest.ammonia,
                        salinitas=latest.salinitas,
                        timestamp=latest.timestamp.replace(tzinfo=timezone.utc)
                    )
                
                # Format historical data
                historical_summary = [
                    schemas.SensorDataSummary(
                        suhu=data.suhu,
                        ph=data.ph,
                        do=data.do,
                        tds=data.tds,
                        ammonia=data.ammonia,
                        salinitas=data.salinitas,
                        timestamp=data.timestamp.replace(tzinfo=timezone.utc)
                    ) for data in historical
                ]
                
                device_data.append(schemas.DeviceMonitoring(
                    id=device.id,
                    name=device.name,
                    latest_data=latest_summary,  # Bisa None
                    historical_data=historical_summary
                ))

            response.append(schemas.KolamMonitoring(
                id=kolam.id,
                nama=kolam.nama,
                devices=device_data
            ))

        return schemas.MonitoringResponse(
            kolam_list=response,
            current_kolam_id=kolams[0].id if kolams else None,
            current_device_id=devices[0].id if devices else None
        )

    except Exception as e:
        logger.exception("Monitoring query failed for user_id=%s", current_user.id)
        raise HTTPException(
            status_code=500,
            detail=f"Error retrieving monitoring data: {str(e)}"
        )
