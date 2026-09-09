from fastapi import FastAPI, HTTPException
import os
from fastapi.middleware.cors import CORSMiddleware
from app.routers import (
    admin,
    users, 
    devices, 
    tambak, 
    kolam, 
    sensor, 
    monitoring, 
    export,
    device_threshold,
    notifications
)
from app.background_tasks import start_background_task
from app.database import engine, Base, IS_SQLITE
from sqlalchemy import inspect, text
import sqlite3
import logging
from prometheus_fastapi_instrumentator import Instrumentator

logger = logging.getLogger(__name__)

app = FastAPI(title="AquaNotes API", version="2.0.0")

# Prometheus Instrumentation
Instrumentator().instrument(app).expose(app)

cors_origins = [origin.strip() for origin in os.getenv("CORS_ORIGINS", "*").split(",") if origin.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=cors_origins != ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(admin.router)
app.include_router(users.router)
app.include_router(devices.router)
app.include_router(tambak.router)
app.include_router(kolam.router)
app.include_router(sensor.router)
app.include_router(monitoring.router)
app.include_router(export.router)
app.include_router(device_threshold.router)
app.include_router(notifications.router)


@app.get("/health", tags=["System"])
def health():
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return {"status": "ok"}
    except Exception:
        logger.exception("Database health check failed")
        raise HTTPException(status_code=503, detail="Service unavailable")

# PERBAIKAN: Fungsi untuk migrasi kolom baru
def migrate_database():
    if not IS_SQLITE:
        inspector = inspect(engine)
        if inspector.has_table("users"):
            columns = {column["name"] for column in inspector.get_columns("users")}
            if "role" not in columns:
                with engine.begin() as connection:
                    connection.exec_driver_sql(
                        "ALTER TABLE users ADD COLUMN role VARCHAR(20) NOT NULL DEFAULT 'user'"
                    )
                logger.info("Added column: users.role")
            if "email_verified" not in columns:
                with engine.begin() as connection:
                    connection.exec_driver_sql(
                        "ALTER TABLE users ADD COLUMN email_verified BOOLEAN NOT NULL DEFAULT TRUE"
                    )
                logger.info("Added column: users.email_verified")
        if inspector.has_table("devices"):
            device_columns = inspector.get_columns("devices")
            columns = {column["name"] for column in device_columns}
            if "deactivation_scheduled_at" not in columns:
                with engine.begin() as connection:
                    connection.exec_driver_sql("ALTER TABLE devices ADD COLUMN deactivation_scheduled_at TIMESTAMP")
                logger.info("Added column: devices.deactivation_scheduled_at")
            status_column = next((column for column in device_columns if column["name"] == "status"), None)
            status_length = getattr(status_column["type"], "length", None) if status_column else None
            if status_length is not None and status_length < 20:
                with engine.begin() as connection:
                    connection.exec_driver_sql("ALTER TABLE devices ALTER COLUMN status TYPE VARCHAR(20)")
                logger.info("Expanded column: devices.status")
        return
    try:
        # Cek apakah kolom sudah ada
        conn = sqlite3.connect(engine.url.database, timeout=30)
        cursor = conn.cursor()

        cursor.execute("PRAGMA table_info(users)")
        user_columns = [info[1] for info in cursor.fetchall()]
        if user_columns and 'role' not in user_columns:
            cursor.execute(
                "ALTER TABLE users ADD COLUMN role VARCHAR(20) NOT NULL DEFAULT 'user'"
            )
            logger.info("Added column: users.role")
        if user_columns and 'email_verified' not in user_columns:
            cursor.execute(
                "ALTER TABLE users ADD COLUMN email_verified BOOLEAN NOT NULL DEFAULT 1"
            )
            logger.info("Added column: users.email_verified")
        
        # Cek tabel devices
        cursor.execute("PRAGMA table_info(devices)")
        columns = [info[1] for info in cursor.fetchall()]
        
        # Tambahkan kolom yang belum ada
        if 'last_seen' not in columns:
            cursor.execute("ALTER TABLE devices ADD COLUMN last_seen DATETIME")
            logger.info("Added column: last_seen")
        
        if 'status' not in columns:
            cursor.execute("ALTER TABLE devices ADD COLUMN status VARCHAR(10) DEFAULT 'offline'")
            logger.info("Added column: status")
        
        if 'connection_interval' not in columns:
            cursor.execute("ALTER TABLE devices ADD COLUMN connection_interval INTEGER DEFAULT 5")
            logger.info("Added column: connection_interval")

        if 'deactivation_scheduled_at' not in columns:
            cursor.execute("ALTER TABLE devices ADD COLUMN deactivation_scheduled_at DATETIME")
            logger.info("Added column: deactivation_scheduled_at")
        
        conn.commit()
        conn.close()
        
    except Exception as e:
        logger.error(f"Database migration error: {str(e)}")

# Create tables and start background task on startup
@app.on_event("startup")
async def startup_event():
    # Jalankan migrasi sebelum membuat tabel
    migrate_database()
    
    # Buat semua tabel
    Base.metadata.create_all(bind=engine)
    
    # Jalankan background tasks
    if os.getenv("START_BACKGROUND_TASKS", "true").lower() in {"1", "true", "yes"}:
        start_background_task()
    logger.info("Application startup complete")
