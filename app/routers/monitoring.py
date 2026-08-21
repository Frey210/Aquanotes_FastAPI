from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from datetime import datetime, timedelta
from typing import Optional
import logging
from app import models, schemas, database, auth
from app.assignments import get_active_assignment

router = APIRouter(prefix="/monitoring", tags=["Monitoring"])
logger = logging.getLogger(__name__)

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
                        timestamp=latest.timestamp
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
                        timestamp=data.timestamp
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
