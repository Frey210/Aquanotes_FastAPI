from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import (
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
from app.database import engine, Base
import sqlite3
import logging

logger = logging.getLogger(__name__)

app = FastAPI(title="AquaNotes API", version="2.0.0")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(users.router)
app.include_router(devices.router)
app.include_router(tambak.router)
app.include_router(kolam.router)
app.include_router(sensor.router)
app.include_router(monitoring.router)
app.include_router(export.router)
app.include_router(device_threshold.router)
app.include_router(notifications.router)

# PERBAIKAN: Fungsi untuk migrasi kolom baru
def migrate_database():
    try:
        # Cek apakah kolom sudah ada
        conn = sqlite3.connect('aquanotes.db')
        cursor = conn.cursor()
        
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
    start_background_task()
    logger.info("Application startup complete")