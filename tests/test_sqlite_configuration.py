import unittest

from app.database import engine


class SQLiteConfigurationTest(unittest.TestCase):
    def test_busy_timeout_is_30_seconds(self):
        with engine.connect() as connection:
            timeout = connection.exec_driver_sql("PRAGMA busy_timeout").scalar_one()
            self.assertEqual(timeout, 30000)

    def test_foreign_keys_are_enabled(self):
        with engine.connect() as connection:
            enabled = connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one()
            self.assertEqual(enabled, 1)


if __name__ == "__main__":
    unittest.main()
