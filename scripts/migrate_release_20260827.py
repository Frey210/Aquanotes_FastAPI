import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import inspect, text

from app import models  # noqa: F401
from app.database import Base, IS_SQLITE, engine
from app.main import migrate_database

SEQUENCE_TABLES = (
    "users", "tambak", "devices", "kolam", "device_assignments",
    "sensor_data", "notifications", "audit_logs", "maintenance_requests", "email_tokens",
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrasi aditif rilis web/admin Aquanotes")
    parser.add_argument("--apply", action="store_true", help="Terapkan migrasi ke DATABASE_URL")
    args = parser.parse_args()
    if not args.apply:
        raise SystemExit("Tidak ada perubahan. Jalankan kembali dengan --apply setelah backup tervalidasi.")
    if IS_SQLITE:
        raise SystemExit("Rilis produksi ini hanya boleh dimigrasikan pada PostgreSQL.")

    migrate_database()
    Base.metadata.create_all(bind=engine)
    inspector = inspect(engine)
    with engine.begin() as connection:
        for table in SEQUENCE_TABLES:
            if not inspector.has_table(table):
                continue
            sequence = connection.execute(
                text("SELECT pg_get_serial_sequence(:table, 'id')"), {"table": table}
            ).scalar()
            if sequence:
                connection.execute(
                    text(f"SELECT setval(:sequence, COALESCE(MAX(id), 1), MAX(id) IS NOT NULL) FROM {table}"),
                    {"sequence": sequence},
                )
    print("Migrasi rilis selesai; schema aditif dan sequence PostgreSQL telah diselaraskan.")


if __name__ == "__main__":
    main()
