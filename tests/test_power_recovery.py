import importlib.util
import json
from pathlib import PurePosixPath
import unittest
from unittest.mock import MagicMock, patch

spec = importlib.util.spec_from_file_location("bootstrap", "deployment/recovery/aquanotes-bootstrap.py")
bootstrap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)


class ReleasePath(PurePosixPath):
    def is_file(self):
        return True


class PowerRecoveryTest(unittest.TestCase):
    def info(self, image="aquanotes-api:current", files="/home/dockeradmin/releases/current/compose.yml"):
        return {"Image": "sha256:current", "Config": {"Image": image, "Labels": {
            "com.docker.compose.project": "stage2",
            "com.docker.compose.project.config_files": files,
        }}}

    def test_preserves_deployed_image_and_never_builds_or_pulls(self):
        with patch.object(bootstrap, "Path", ReleasePath), patch.object(bootstrap, "run", side_effect=[json.dumps({"services": {"api": {"image": "aquanotes-api:current"}}}), "sha256:current"]):
            command = bootstrap.compose_command("api", self.info(), {})
        self.assertIn("--no-build", command)
        self.assertEqual(command[command.index("--pull") + 1], "never")
        self.assertEqual(command[-1], "api")

    def test_rejects_image_downgrade_and_untrusted_file_path(self):
        with patch.object(bootstrap, "Path", ReleasePath), patch.object(bootstrap, "run", return_value=json.dumps({"services": {"api": {"image": "old-image"}}})):
            with self.assertRaises(RuntimeError):
                bootstrap.compose_command("api", self.info(), {})
            with self.assertRaises(RuntimeError):
                bootstrap.compose_command("api", self.info(files="/tmp/compose.yml"), {})

    def test_healthy_application_is_not_recreated(self):
        with patch.object(bootstrap, "healthy", return_value=True), patch.object(bootstrap, "run") as run:
            bootstrap.main()
        run.assert_not_called()

    def test_changed_local_image_tag_is_rejected(self):
        with patch.object(bootstrap, "Path", ReleasePath), patch.object(bootstrap, "run", side_effect=[json.dumps({"services": {"api": {"image": "aquanotes-api:current"}}}), "sha256:other"]):
            with self.assertRaises(RuntimeError):
                bootstrap.compose_command("api", self.info(), {})

    def test_retry_does_not_recreate_containers_twice_in_one_boot(self):
        with patch.object(bootstrap, "healthy", return_value=False), patch.object(bootstrap.socket, "create_connection", return_value=MagicMock()), patch.object(bootstrap, "compose_command", return_value=["restore"]), patch.object(bootstrap, "Path") as path, patch.object(bootstrap, "run", return_value=json.dumps([self.info()])) as run:
            path.return_value.__truediv__.return_value.exists.return_value = True
            with self.assertRaises(RuntimeError):
                bootstrap.main()
        self.assertEqual(run.call_count, 2)
        self.assertTrue(all(call.args[0][:2] == ["docker", "inspect"] for call in run.call_args_list))


if __name__ == "__main__":
    unittest.main()
