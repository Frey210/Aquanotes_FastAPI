from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from datetime import datetime
import csv
import io
from app import models, database
from app.schemas import ExportRequest
from app.auth import get_current_user
from app.timezones import tambak_time_to_utc, utc_to_tambak_time

router = APIRouter(prefix="/export", tags=["Export Data"])

@router.post("/csv")
def export_to_csv(
    request: ExportRequest,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user),
):
    # Validasi tanggal
    if request.start_date > request.end_date:
        raise HTTPException(
            status_code=400,
            detail="Start date must be before end date"
        )

    tambak = db.query(models.Tambak).join(models.Kolam).filter(
        models.Kolam.device_id == request.device_id,
        models.Tambak.user_id == current_user.id,
    ).first()
    start_utc = tambak_time_to_utc(datetime.combine(request.start_date, datetime.min.time()), tambak)
    end_utc = tambak_time_to_utc(datetime.combine(request.end_date, datetime.max.time()), tambak)

    # Query data
    sensor_data = db.query(models.SensorData).join(models.DeviceAssignment).filter(
        models.SensorData.device_id == request.device_id,
        models.DeviceAssignment.user_id == current_user.id,
        models.SensorData.timestamp >= start_utc,
        models.SensorData.timestamp <= end_utc,
    ).order_by(models.SensorData.timestamp).all()

    if not sensor_data:
        raise HTTPException(status_code=404, detail="No data found")

    # Generate CSV
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Header
    writer.writerow([
        "Timestamp", "Temperature (°C)", "pH", 
        "Dissolved Oxygen (mg/L)", "TDS (ppm)",
        "Ammonia (mg/L)", "Salinity (ppt)"
    ])
    
    # Rows
    for data in sensor_data:
        writer.writerow([
            utc_to_tambak_time(data.timestamp, tambak).isoformat(),
            data.suhu,
            data.ph,
            data.do,
            data.tds,
            data.ammonia,
            data.salinitas
        ])
    
    # Return as downloadable file
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": (
                f"attachment; filename="
                f"sensor_data_{request.device_id}_"
                f"{request.start_date}_{request.end_date}.csv"
            )
        }
    )
