from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from datetime import datetime
import csv
import io
from app import models, database
from app.schemas import ExportRequest

router = APIRouter(prefix="/export", tags=["Export Data"])

@router.post("/csv")
def export_to_csv(
    request: ExportRequest,
    db: Session = Depends(database.get_db)
):
    # Validasi tanggal
    if request.start_date > request.end_date:
        raise HTTPException(
            status_code=400,
            detail="Start date must be before end date"
        )

    # Query data
    sensor_data = db.query(models.SensorData).filter(
        models.SensorData.device_id == request.device_id,
        models.SensorData.timestamp >= datetime.combine(request.start_date, datetime.min.time()),
        models.SensorData.timestamp <= datetime.combine(request.end_date, datetime.max.time())
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
            data.timestamp.isoformat(),
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