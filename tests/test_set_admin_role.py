import tempfile
import unittest
from pathlib import Path

from scripts.set_admin_role import read_credentials


class AdminCredentialFileTest(unittest.TestCase):
    def test_reads_email_and_password_without_cli_secret(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "admin.txt"
            path.write_text("Admin@Example.com\nstrong-password\n", encoding="utf-8")
            self.assertEqual(read_credentials(str(path)), ("admin@example.com", "strong-password"))


if __name__ == "__main__":
    unittest.main()
