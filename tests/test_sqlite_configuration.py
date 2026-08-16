import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.database import configure_sqlite, engine


class SQLiteConfigurationTest(unittest.TestCase):
    def test_wal_and_busy_timeout_are_enabled(self):
        with tempfile.TemporaryDirectory() as directory:
            connection = sqlite3.connect(Path(directory) / "test.db")
            configure_sqlite(connection)

            self.assertEqual(connection.execute("PRAGMA journal_mode").fetchone()[0], "wal")
            self.assertEqual(connection.execute("PRAGMA busy_timeout").fetchone()[0], 30000)
            connection.close()

        with engine.connect() as connection:
            timeout = connection.exec_driver_sql("PRAGMA busy_timeout").scalar_one()
            self.assertEqual(timeout, 30000)


if __name__ == "__main__":
    unittest.main()
