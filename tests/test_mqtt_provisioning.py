import os
from unittest.mock import patch

from app.mqtt_provisioning import provision_device


def test_provisioning_keeps_password_out_of_process_arguments():
    env = {
        "MQTT_PROVISIONING_ENABLED": "true",
        "MQTT_PROVISIONING_HOST": "broker",
    }
    with patch.dict(os.environ, env, clear=True), patch("subprocess.run") as run:
        run.return_value.returncode = 0
        result = provision_device("AER2023AQ0032")

    command = run.call_args.args[0]
    assert result["mqtt_password"] not in command
    assert run.call_args.kwargs["input"] == result["mqtt_password"] + "\n"
    assert '#define DEVICE_UID "AER2023AQ0032"' in result["secrets_h"]
