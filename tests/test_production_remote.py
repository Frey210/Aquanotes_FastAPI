import unittest
import tempfile
from pathlib import Path

from scripts.production_remote import credentials


class ProductionRemoteCredentialsTest(unittest.TestCase):
    def test_reads_docker_tailscale_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "credentials.md"
            path.write_text(
                "## Docker/Portainer baru\n"
                "- Host Tailscale: `100.64.0.1`\n"
                "- User SSH: `operator`\n"
                "- Password SSH: `secret-value`\n",
                encoding="utf-8",
            )
            self.assertEqual(credentials(str(path)), ("100.64.0.1", "operator", "secret-value"))


if __name__ == "__main__":
    unittest.main()
