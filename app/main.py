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
    notifications,
    ota,
)
from app.background_tasks import start_background_task
from app.mqtt_consumer import start_mqtt_consumer, stop_mqtt_consumer
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
app.include_router(ota.router)


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
            if "mqtt_credential_status" not in columns:
                with engine.begin() as connection:
                    connection.exec_driver_sql(
                        "ALTER TABLE devices ADD COLUMN mqtt_credential_status VARCHAR(20) NOT NULL DEFAULT 'unprovisioned'"
                    )
                logger.info("Added column: devices.mqtt_credential_status")
            if "mqtt_credential_updated_at" not in columns:
                with engine.begin() as connection:
                    connection.exec_driver_sql("ALTER TABLE devices ADD COLUMN mqtt_credential_updated_at TIMESTAMP")
                logger.info("Added column: devices.mqtt_credential_updated_at")
            if "current_firmware_version" not in columns:
                with engine.begin() as connection:
                    connection.exec_driver_sql("ALTER TABLE devices ADD COLUMN current_firmware_version VARCHAR(64)")
                logger.info("Added column: devices.current_firmware_version")
            if "power_profile" not in columns:
                with engine.begin() as connection:
                    connection.exec_driver_sql(
                        "ALTER TABLE devices ADD COLUMN power_profile VARCHAR(20) NOT NULL DEFAULT 'portable'"
                    )
                logger.info("Added column: devices.power_profile")
            with engine.begin() as connection:
                connection.exec_driver_sql(
                    "UPDATE devices SET mqtt_credential_status='active', mqtt_credential_updated_at=CURRENT_TIMESTAMP "
                    "WHERE uid='AER2023AQ0029' AND mqtt_credential_status='unprovisioned'"
                )
            status_column = next((column for column in device_columns if column["name"] == "status"), None)
            status_length = getattr(status_column["type"], "length", None) if status_column else None
            if status_length is not None and status_length < 20:
                with engine.begin() as connection:
                    connection.exec_driver_sql("ALTER TABLE devices ALTER COLUMN status TYPE VARCHAR(20)")
                logger.info("Expanded column: devices.status")
        if inspector.has_table("firmware_releases"):
            release_columns = {
                column["name"] for column in inspect(engine).get_columns("firmware_releases")
            }
            if "signature" not in release_columns:
                with engine.begin() as connection:
                    connection.exec_driver_sql("ALTER TABLE firmware_releases ADD COLUMN signature TEXT")
                logger.info("Added column: firmware_releases.signature")
            if "signing_key_id" not in release_columns:
                with engine.begin() as connection:
                    connection.exec_driver_sql(
                        "ALTER TABLE firmware_releases ADD COLUMN signing_key_id VARCHAR(32)"
                    )
                logger.info("Added column: firmware_releases.signing_key_id")
            for name, definition in (
                ("factory_artifact_filename", "VARCHAR(255)"),
                ("factory_sha256", "VARCHAR(64)"),
                ("factory_size_bytes", "INTEGER"),
                ("factory_signature", "TEXT"),
                ("factory_only", "BOOLEAN NOT NULL DEFAULT FALSE"),
            ):
                if name not in release_columns:
                    with engine.begin() as connection:
                        connection.exec_driver_sql(
                            f"ALTER TABLE firmware_releases ADD COLUMN {name} {definition}"
                        )
                    logger.info("Added column: firmware_releases.%s", name)
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

        if 'mqtt_credential_status' not in columns:
            cursor.execute("ALTER TABLE devices ADD COLUMN mqtt_credential_status VARCHAR(20) NOT NULL DEFAULT 'unprovisioned'")
            logger.info("Added column: mqtt_credential_status")

        if 'mqtt_credential_updated_at' not in columns:
            cursor.execute("ALTER TABLE devices ADD COLUMN mqtt_credential_updated_at DATETIME")
            logger.info("Added column: mqtt_credential_updated_at")

        if 'current_firmware_version' not in columns:
            cursor.execute("ALTER TABLE devices ADD COLUMN current_firmware_version VARCHAR(64)")
            logger.info("Added column: current_firmware_version")

        if 'power_profile' not in columns:
            cursor.execute("ALTER TABLE devices ADD COLUMN power_profile VARCHAR(20) NOT NULL DEFAULT 'portable'")
            logger.info("Added column: power_profile")

        cursor.execute("PRAGMA table_info(firmware_releases)")
        release_columns = [info[1] for info in cursor.fetchall()]
        if release_columns and 'signature' not in release_columns:
            cursor.execute("ALTER TABLE firmware_releases ADD COLUMN signature TEXT")
            logger.info("Added column: firmware_releases.signature")
        if release_columns and 'signing_key_id' not in release_columns:
            cursor.execute("ALTER TABLE firmware_releases ADD COLUMN signing_key_id VARCHAR(32)")
            logger.info("Added column: firmware_releases.signing_key_id")
        for name, definition in (
            ('factory_artifact_filename', 'VARCHAR(255)'),
            ('factory_sha256', 'VARCHAR(64)'),
            ('factory_size_bytes', 'INTEGER'),
            ('factory_signature', 'TEXT'),
            ('factory_only', 'BOOLEAN NOT NULL DEFAULT 0'),
        ):
            if release_columns and name not in release_columns:
                cursor.execute(f"ALTER TABLE firmware_releases ADD COLUMN {name} {definition}")
                logger.info("Added column: firmware_releases.%s", name)

        cursor.execute(
            "UPDATE devices SET mqtt_credential_status='active', mqtt_credential_updated_at=CURRENT_TIMESTAMP "
            "WHERE uid='AER2023AQ0029' AND mqtt_credential_status='unprovisioned'"
        )
        
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
    start_mqtt_consumer()
    logger.info("Application startup complete")


@app.on_event("shutdown")
async def shutdown_event():
    stop_mqtt_consumer()
