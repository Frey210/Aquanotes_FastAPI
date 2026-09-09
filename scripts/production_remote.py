import argparse
import base64
import re
from pathlib import Path

import paramiko


def credentials(path: str) -> tuple[str, str, str]:
    text = Path(path).read_text(encoding="utf-8")
    section = re.search(r"(?ims)^##\s*Docker/Portainer baru.*?(?=^##\s|\Z)", text)
    if not section:
        raise ValueError("Docker/Portainer credential section not found")

    def line(label: str) -> str:
        match = re.search(rf"(?im)^-?\s*{re.escape(label)}\s*:\s*(.+)$", section.group(0))
        if not match:
            raise ValueError(f"Missing credential field: {label}")
        return match.group(1)

    host = re.search(r"(?:\d{1,3}\.){3}\d{1,3}", line("Host Tailscale"))
    if not host:
        raise ValueError("Invalid Tailscale host")
    return host.group(0), line("User SSH").split("`")[1], line("Password SSH").split("`")[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--credentials", default="secrets/backend-credentials.md")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--exec-base64")
    action.add_argument("--put", nargs=2, metavar=("LOCAL", "REMOTE"))
    action.add_argument("--get", nargs=2, metavar=("REMOTE", "LOCAL"))
    args = parser.parse_args()

    host, username, password = credentials(args.credentials)
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(host, username=username, password=password, timeout=15,
                   allow_agent=False, look_for_keys=False)
    try:
        if args.put:
            with client.open_sftp() as sftp:
                sftp.put(*args.put)
            print("upload=ok")
            return
        if args.get:
            with client.open_sftp() as sftp:
                sftp.get(*args.get)
            print("download=ok")
            return
        command = base64.b64decode(args.exec_base64).decode("utf-8")
        _, stdout, stderr = client.exec_command(command)
        output, error = stdout.read(), stderr.read()
        print(output.decode(), end="")
        print(error.decode(), end="")
        raise SystemExit(stdout.channel.recv_exit_status())
    finally:
        client.close()


if __name__ == "__main__":
    main()
