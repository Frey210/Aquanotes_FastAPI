import argparse
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


MIGRATION = "20260822_assignment_history"


def migrate(database: Path, backup: Path):
    database = database.resolve()
    backup = backup.resolve()
    if not database.is_file():
        raise FileNotFoundError(database)
    if backup.exists():
        raise FileExistsError(backup)

    source = sqlite3.connect(database, timeout=30)
    source.execute("PRAGMA busy_timeout=30000")
    if source.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        source.close()
        raise RuntimeError("Source database failed integrity_check")

    backup.parent.mkdir(parents=True, exist_ok=True)
    target = sqlite3.connect(backup)
    source.backup(target)
    target.close()

    before = source.execute("SELECT count(*) FROM sensor_data").fetchone()[0]
    try:
        source.execute("BEGIN IMMEDIATE")
        source.execute("""
            CREATE TABLE IF NOT EXISTS app_migrations (
                name TEXT PRIMARY KEY,
                applied_at DATETIME NOT NULL,
                sensor_max_id INTEGER NOT NULL
            )
        """)
        if source.execute(
            "SELECT 1 FROM app_migrations WHERE name = ?", (MIGRATION,)
        ).fetchone():
            source.rollback()
            return {"status": "already_applied", "sensor_rows": before}

        source.execute("""
            CREATE TABLE device_assignments (
                id INTEGER PRIMARY KEY,
                device_id INTEGER NOT NULL REFERENCES devices(id),
                user_id INTEGER NOT NULL REFERENCES users(id),
                kolam_id INTEGER,
                tambak_id INTEGER,
                started_at DATETIME NOT NULL,
                ended_at DATETIME,
                is_legacy BOOLEAN NOT NULL DEFAULT 0
            )
        """)
        columns = {
            row[1] for row in source.execute("PRAGMA table_info(sensor_data)")
        }
        if "assignment_id" not in columns:
            source.execute(
                "ALTER TABLE sensor_data ADD COLUMN assignment_id INTEGER "
                "REFERENCES device_assignments(id)"
            )

        source.execute("""
            CREATE INDEX ix_device_assignments_user_device
            ON device_assignments(user_id, device_id)
        """)
        source.execute("""
            CREATE UNIQUE INDEX ux_device_assignments_active
            ON device_assignments(device_id) WHERE ended_at IS NULL
        """)
        source.execute("""
            CREATE INDEX ix_sensor_data_assignment_timestamp
            ON sensor_data(assignment_id, timestamp)
        """)
        source.execute("""
            INSERT INTO device_assignments (
                device_id, user_id, kolam_id, tambak_id,
                started_at, ended_at, is_legacy
            )
            SELECT
                d.id,
                d.user_id,
                k.id,
                k.tambak_id,
                COALESCE(MIN(s.timestamp), CURRENT_TIMESTAMP),
                NULL,
                1
            FROM devices d
            LEFT JOIN kolam k ON k.device_id = d.id
            LEFT JOIN sensor_data s ON s.device_id = d.id
            WHERE d.user_id IS NOT NULL
            GROUP BY d.id, d.user_id, k.id, k.tambak_id
        """)
        source.execute("""
            UPDATE sensor_data
            SET assignment_id = (
                SELECT a.id
                FROM device_assignments a
                WHERE a.device_id = sensor_data.device_id
                  AND a.is_legacy = 1
            )
            WHERE assignment_id IS NULL
              AND EXISTS (
                  SELECT 1 FROM device_assignments a
                  WHERE a.device_id = sensor_data.device_id
                    AND a.is_legacy = 1
              )
        """)
        sensor_max_id = source.execute(
            "SELECT COALESCE(MAX(id), 0) FROM sensor_data"
        ).fetchone()[0]
        source.execute(
            "INSERT INTO app_migrations(name, applied_at, sensor_max_id) "
            "VALUES (?, ?, ?)",
            (MIGRATION, datetime.now(timezone.utc).isoformat(), sensor_max_id),
        )
        source.commit()
    except Exception:
        source.rollback()
        raise

    after = source.execute("SELECT count(*) FROM sensor_data").fetchone()[0]
    assigned = source.execute(
        "SELECT count(*) FROM sensor_data WHERE assignment_id IS NOT NULL"
    ).fetchone()[0]
    foreign_key_errors = list(source.execute("PRAGMA foreign_key_check"))
    source.close()
    if before != after or foreign_key_errors:
        raise RuntimeError(
            f"Verification failed: rows {before}->{after}, "
            f"foreign_key_errors={len(foreign_key_errors)}"
        )
    return {"status": "applied", "sensor_rows": after, "assigned_rows": assigned}


def finalize(database: Path):
    """Reconcile the short old-app window. Run only while the API is stopped."""
    connection = sqlite3.connect(database.resolve(), timeout=30)
    connection.execute("PRAGMA busy_timeout=30000")
    try:
        connection.execute("BEGIN IMMEDIATE")
        cutoff_row = connection.execute(
            "SELECT sensor_max_id FROM app_migrations WHERE name = ?",
            (MIGRATION,),
        ).fetchone()
        if not cutoff_row:
            raise RuntimeError("Assignment migration has not been applied")
        cutoff = cutoff_row[0]
        now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()

        devices = connection.execute("""
            SELECT d.id, d.user_id, k.id, k.tambak_id
            FROM devices d
            LEFT JOIN kolam k ON k.device_id = d.id
        """).fetchall()
        for device_id, user_id, kolam_id, tambak_id in devices:
            active = connection.execute("""
                SELECT id, user_id, kolam_id, tambak_id
                FROM device_assignments
                WHERE device_id = ? AND ended_at IS NULL
            """, (device_id,)).fetchone()
            expected = (user_id, kolam_id, tambak_id)
            if active and active[1:] == expected:
                continue
            if active:
                connection.execute(
                    "UPDATE device_assignments SET ended_at = ? WHERE id = ?",
                    (now, active[0]),
                )
            if user_id is not None:
                connection.execute("""
                    INSERT INTO device_assignments (
                        device_id, user_id, kolam_id, tambak_id,
                        started_at, ended_at, is_legacy
                    ) VALUES (?, ?, ?, ?, ?, NULL, 0)
                """, (device_id, user_id, kolam_id, tambak_id, now))

        connection.execute("""
            UPDATE sensor_data
            SET assignment_id = (
                SELECT a.id
                FROM device_assignments a
                JOIN devices d ON d.id = a.device_id
                WHERE a.device_id = sensor_data.device_id
                  AND a.user_id = d.user_id
                  AND a.ended_at IS NULL
            )
            WHERE id > ? AND assignment_id IS NULL
        """, (cutoff,))
        connection.commit()
    except Exception:
        connection.rollback()
        raise

    unassigned = connection.execute("""
        SELECT count(*)
        FROM sensor_data s
        JOIN devices d ON d.id = s.device_id
        WHERE s.id > ? AND s.assignment_id IS NULL AND d.user_id IS NOT NULL
    """, (cutoff,)).fetchone()[0]
    mismatches = connection.execute("""
        SELECT count(*)
        FROM devices d
        LEFT JOIN kolam k ON k.device_id = d.id
        LEFT JOIN device_assignments a
          ON a.device_id = d.id AND a.ended_at IS NULL
        WHERE (d.user_id IS NULL AND a.id IS NOT NULL)
           OR (d.user_id IS NOT NULL AND (
               a.id IS NULL OR a.user_id != d.user_id
               OR a.kolam_id IS NOT k.id OR a.tambak_id IS NOT k.tambak_id
           ))
    """).fetchone()[0]
    connection.close()
    if unassigned or mismatches:
        raise RuntimeError(
            f"Finalization failed: unassigned={unassigned}, mismatches={mismatches}"
        )
    return {"status": "finalized", "cutoff": cutoff}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--backup", type=Path)
    parser.add_argument("--finalize", action="store_true")
    args = parser.parse_args()
    if args.finalize:
        print(finalize(args.database))
    elif args.backup:
        print(migrate(args.database, args.backup))
    else:
        parser.error("--backup is required unless --finalize is used")


if __name__ == "__main__":
    main()
