import unittest
from pathlib import Path


class AdminSecurityTest(unittest.TestCase):
    def test_admin_key_is_not_logged_or_reflected(self):
        source = (Path(__file__).parents[1] / "app" / "routers" / "admin.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("Received API Key:", source)
        self.assertNotIn("Expected API Key:", source)
        self.assertNotIn("Invalid API Key. Received:", source)
        self.assertNotIn('"default-admin-secret"', source)


if __name__ == "__main__":
    unittest.main()
