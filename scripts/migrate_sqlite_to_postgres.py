import os
import sqlite3
import sys
from pathlib import Path

import psycopg
from psycopg import sql

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


TABLES = (
    "users",
    "tambak",
    "devices",
    "kolam",
    "device_assignments",
    "sensor_data",
    "notifications",
    "auth_tokens",
    "threshold_alert_states",
)
BOOLEAN_COLUMNS = {
    "device_assignments": {"is_legacy"},
    "notifications": {"is_read", "fcm_sent"},
    "threshold_alert_states": {"is_active"},
}
SEQUENCE_TABLES = (
    "users",
    "tambak",
    "devices",
    "kolam",
    "device_assignments",
    "sensor_data",
    "notifications",
)


def copy_table(source, target, table, batch_size=10_000):
    columns = [row[1] for row in source.execute(f'PRAGMA table_info("{table}")')]
    if not columns:
        raise RuntimeError(f"Source table is missing: {table}")

    query = sql.SQL("COPY {} ({}) FROM STDIN").format(
        sql.Identifier(table),
        sql.SQL(", ").join(map(sql.Identifier, columns)),
    )
    booleans = BOOLEAN_COLUMNS.get(table, set())
    indexes = {columns.index(column) for column in booleans if column in columns}
    copied = 0

    cursor = source.execute(f'SELECT * FROM "{table}" ORDER BY rowid')
    with target.cursor().copy(query) as copy:
        while rows := cursor.fetchmany(batch_size):
            for row in rows:
                values = list(row)
                for index in indexes:
                    values[index] = None if values[index] is None else bool(values[index])
                copy.write_row(values)
            copied += len(rows)
    return copied


def main():
    if len(sys.argv) != 2:
        raise SystemExit("Usage: migrate_sqlite_to_postgres.py <sqlite-backup>")

    source_path = Path(sys.argv[1]).resolve()
    if not source_path.is_file():
        raise SystemExit(f"SQLite backup not found: {source_path}")

    database_url = os.environ.get("DATABASE_URL")
    if not database_url or not database_url.startswith("postgresql"):
        raise SystemExit("DATABASE_URL must point to the target PostgreSQL database")

    os.environ["DATABASE_URL"] = database_url
    from app.database import Base, engine
    from app import models  # noqa: F401

    Base.metadata.create_all(engine)
    psycopg_url = database_url.replace("postgresql+psycopg://", "postgresql://", 1)

    source = sqlite3.connect(f"file:{source_path.as_posix()}?mode=ro", uri=True)
    source.execute("PRAGMA query_only=ON")
    with psycopg.connect(psycopg_url) as target:
        existing = target.execute(
            "SELECT EXISTS (SELECT 1 FROM users LIMIT 1)"
        ).fetchone()[0]
        if existing:
            raise RuntimeError("Target is not empty; use a fresh database for rehearsal")

        for table in TABLES:
            count = copy_table(source, target, table)
            print(f"{table}: {count}", flush=True)
            target.commit()

        for table in SEQUENCE_TABLES:
            target.execute(
                sql.SQL(
                    "SELECT setval(pg_get_serial_sequence(%s, 'id'), "
                    "COALESCE(MAX(id), 1), MAX(id) IS NOT NULL) FROM {}"
                ).format(sql.Identifier(table)),
                (table,),
            )
        target.commit()
    source.close()


if __name__ == "__main__":
    main()
