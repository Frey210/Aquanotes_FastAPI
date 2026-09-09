import argparse
import os
import smtplib
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import inspect, text

from app.database import IS_SQLITE, engine

REQUIRED_ENV = (
    "DATABASE_URL", "ADMIN_API_KEY", "SMTP_EMAIL", "SMTP_APP_PASSWORD",
    "FRONTEND_URL", "CORS_ORIGINS",
)
REQUIRED_TABLES = ("users", "devices", "email_tokens", "audit_logs", "maintenance_requests")
SEQUENCE_TABLES = (
    "users", "tambak", "devices", "kolam", "device_assignments",
    "sensor_data", "notifications", "audit_logs", "maintenance_requests", "email_tokens",
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Preflight read-only rilis Aquanotes")
    parser.add_argument("--check-smtp", action="store_true", help="Autentikasi SMTP tanpa mengirim email")
    args = parser.parse_args()
    errors: list[str] = []

    for key in REQUIRED_ENV:
        value = os.getenv(key, "").strip()
        if not value or "replace-with" in value:
            errors.append(f"Environment {key} belum dikonfigurasi")

    frontend_url = os.getenv("FRONTEND_URL", "")
    parsed_frontend = urlparse(frontend_url)
    if parsed_frontend.scheme != "https" or not parsed_frontend.netloc:
        errors.append("FRONTEND_URL produksi harus berupa URL HTTPS")
    origins = [value.strip() for value in os.getenv("CORS_ORIGINS", "").split(",") if value.strip()]
    frontend_origin = f"{parsed_frontend.scheme}://{parsed_frontend.netloc}" if parsed_frontend.netloc else ""
    if "*" in origins or frontend_origin not in origins:
        errors.append("CORS_ORIGINS harus eksplisit dan memuat origin FRONTEND_URL")
    if len("".join(os.getenv("SMTP_APP_PASSWORD", "").split())) != 16:
        errors.append("SMTP_APP_PASSWORD Gmail harus berupa App Password 16 karakter")
    if IS_SQLITE:
        errors.append("DATABASE_URL produksi harus menggunakan PostgreSQL")

    try:
        inspector = inspect(engine)
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            for table in REQUIRED_TABLES:
                if not inspector.has_table(table):
                    errors.append(f"Tabel belum tersedia: {table}")
            if inspector.has_table("users"):
                user_columns = {column["name"] for column in inspector.get_columns("users")}
                for column in ("role", "email_verified"):
                    if column not in user_columns:
                        errors.append(f"Kolom belum tersedia: users.{column}")
            if inspector.has_table("devices"):
                device_columns = {column["name"]: column for column in inspector.get_columns("devices")}
                if "deactivation_scheduled_at" not in device_columns:
                    errors.append("Kolom belum tersedia: devices.deactivation_scheduled_at")
                status_column = device_columns.get("status")
                status_length = getattr(status_column["type"], "length", None) if status_column else None
                if status_length is not None and status_length < 20:
                    errors.append("Kolom devices.status masih lebih pendek dari VARCHAR(20)")
            if not IS_SQLITE:
                for table in SEQUENCE_TABLES:
                    if not inspector.has_table(table):
                        continue
                    sequence = connection.execute(
                        text("SELECT pg_get_serial_sequence(:table, 'id')"), {"table": table}
                    ).scalar()
                    if not sequence:
                        continue
                    maximum = connection.execute(text(f"SELECT COALESCE(MAX(id), 0) FROM {table}")).scalar()
                    last_value, is_called = connection.execute(text(f"SELECT last_value, is_called FROM {sequence}")).one()
                    if maximum and (last_value < maximum or not is_called):
                        errors.append(f"Sequence tertinggal: {table}")
    except Exception as exc:
        errors.append(f"Database tidak siap: {type(exc).__name__}")

    if args.check_smtp and not any(error.startswith("Environment SMTP") for error in errors):
        try:
            with smtplib.SMTP("smtp.gmail.com", 587, timeout=20) as smtp:
                smtp.starttls()
                smtp.login(os.environ["SMTP_EMAIL"], "".join(os.environ["SMTP_APP_PASSWORD"].split()))
        except Exception as exc:
            errors.append(f"SMTP tidak siap: {type(exc).__name__}")

    if errors:
        print("PREFLIGHT GAGAL")
        for error in errors:
            print(f"- {error}")
        raise SystemExit(1)
    print("PREFLIGHT LULUS")


if __name__ == "__main__":
    main()
