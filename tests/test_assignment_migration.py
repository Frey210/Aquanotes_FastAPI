import sqlite3
import tempfile
import unittest
from pathlib import Path

from scripts.migrate_assignment_history import finalize, migrate


class AssignmentMigrationTest(unittest.TestCase):
    def test_backfill_preserves_rows_and_uses_current_owner_and_pond(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "aquanotes.db"
            backup = Path(directory) / "aquanotes.before.db"
            connection = sqlite3.connect(database)
            connection.executescript("""
                PRAGMA foreign_keys=ON;
                CREATE TABLE users (id INTEGER PRIMARY KEY);
                CREATE TABLE devices (
                    id INTEGER PRIMARY KEY,
                    user_id INTEGER REFERENCES users(id)
                );
                CREATE TABLE tambak (id INTEGER PRIMARY KEY);
                CREATE TABLE kolam (
                    id INTEGER PRIMARY KEY,
                    tambak_id INTEGER REFERENCES tambak(id),
                    device_id INTEGER UNIQUE REFERENCES devices(id)
                );
                CREATE TABLE sensor_data (
                    id INTEGER PRIMARY KEY,
                    device_id INTEGER REFERENCES devices(id),
                    timestamp DATETIME
                );
                INSERT INTO users VALUES (15);
                INSERT INTO tambak VALUES (16);
                INSERT INTO devices VALUES (31, 15);
                INSERT INTO devices VALUES (32, NULL);
                INSERT INTO kolam VALUES (7, 16, 31);
                INSERT INTO sensor_data VALUES (1, 31, '2026-08-01 00:00:00');
                INSERT INTO sensor_data VALUES (2, 31, '2026-08-02 00:00:00');
                INSERT INTO sensor_data VALUES (3, 32, '2026-08-03 00:00:00');
            """)
            connection.close()

            result = migrate(database, backup)
            self.assertEqual(result["sensor_rows"], 3)
            self.assertTrue(backup.is_file())

            connection = sqlite3.connect(database)
            assignment = connection.execute("""
                SELECT device_id, user_id, kolam_id, tambak_id, is_legacy
                FROM device_assignments
            """).fetchone()
            self.assertEqual(assignment, (31, 15, 7, 16, 1))
            self.assertEqual(
                connection.execute(
                    "SELECT count(*) FROM sensor_data WHERE assignment_id IS NOT NULL"
                ).fetchone()[0],
                2,
            )
            self.assertEqual(
                connection.execute("SELECT count(*) FROM sensor_data").fetchone()[0],
                3,
            )
            connection.execute(
                "INSERT INTO sensor_data VALUES (4, 31, '2026-08-04 00:00:00', NULL)"
            )
            connection.commit()
            connection.close()

            result = finalize(database)
            self.assertEqual(result["status"], "finalized")
            connection = sqlite3.connect(database)
            self.assertIsNotNone(
                connection.execute(
                    "SELECT assignment_id FROM sensor_data WHERE id = 4"
                ).fetchone()[0]
            )
            self.assertIsNone(
                connection.execute(
                    "SELECT assignment_id FROM sensor_data WHERE id = 3"
                ).fetchone()[0]
            )
            connection.close()


if __name__ == "__main__":
    unittest.main()
