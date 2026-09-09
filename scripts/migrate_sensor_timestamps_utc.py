import argparse

from sqlalchemy import text

from app.database import IS_SQLITE, engine


MIGRATION_NAME = "sensor_timestamp_legacy_utc_v1"


def main() -> None:
    parser = argparse.ArgumentParser(description="Normalize legacy UTC+8 sensor timestamps to UTC.")
    parser.add_argument("--through-id", type=int, required=True)
    parser.add_argument("--hours", type=int, default=8)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not args.apply:
        raise SystemExit("Tidak ada perubahan; tambahkan --apply setelah backup.")
    if IS_SQLITE or args.through_id < 1 or not 0 <= args.hours <= 14:
        raise SystemExit("Migrasi hanya untuk PostgreSQL dengan through-id dan offset yang valid.")

    with engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE IF NOT EXISTS deployment_migrations (
                name VARCHAR(100) PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                details TEXT
            )
        """))
        if connection.execute(
            text("SELECT 1 FROM deployment_migrations WHERE name = :name"),
            {"name": MIGRATION_NAME},
        ).scalar():
            print("Migrasi timestamp sudah pernah diterapkan; tidak ada perubahan.")
            return
        changed = connection.execute(text("""
            UPDATE sensor_data
            SET timestamp = timestamp - (:hours * INTERVAL '1 hour')
            WHERE id <= :through_id
        """), {"hours": args.hours, "through_id": args.through_id}).rowcount
        connection.execute(text("""
            INSERT INTO deployment_migrations (name, details)
            VALUES (:name, :details)
        """), {
            "name": MIGRATION_NAME,
            "details": f"shifted {changed} rows through id {args.through_id} by -{args.hours} hours",
        })
    print(f"Migrasi timestamp selesai: {changed} baris dinormalisasi ke UTC.")


if __name__ == "__main__":
    main()
