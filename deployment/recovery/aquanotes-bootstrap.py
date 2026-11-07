#!/usr/bin/env python3
"""Restore the deployed Aquanotes containers once per boot; never build or pull."""
import json
import os
from pathlib import Path
import socket
import subprocess
import urllib.request

SERVICES = {"api": ("stage2-api-1", "http://192.168.10.64:8000/health"),
            "web": ("stage2-web-1", "http://192.168.10.64:8080/api/health")}


def run(args, env=None):
    return subprocess.check_output(args, env=env, text=True, timeout=60)


def healthy(url):
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            return response.status == 200
    except (OSError, TimeoutError):
        return False


def compose_command(service, info, env):
    config = info["Config"]
    labels = config.get("Labels") or {}
    if labels.get("com.docker.compose.project") != "stage2":
        raise RuntimeError("Unexpected Compose project")
    files = labels.get("com.docker.compose.project.config_files", "").split(",")
    command = ["docker", "compose", "-p", "stage2"]
    for name in files:
        path = Path(name)
        if not path.is_absolute() or ".." in path.parts or not path.is_relative_to("/home/dockeradmin/releases") or not path.is_file():
            raise RuntimeError("Deployed Compose file missing or outside release directory")
        command += ["-f", name]
    resolved = json.loads(run(command + ["config", "--format", "json"], env))
    if resolved["services"][service].get("image") != config["Image"]:
        raise RuntimeError("Refusing to replace the deployed image with a different image")
    if run(["docker", "image", "inspect", config["Image"], "--format", "{{.Id}}"], env).strip() != info["Image"]:
        raise RuntimeError("Deployed image tag changed; manual release verification required")
    return command + ["up", "-d", "--no-deps", "--no-build", "--pull", "never", "--force-recreate", service]


def main():
    if all(healthy(url) for _, url in SERVICES.values()):
        print("Aquanotes already healthy; no changes")
        return
    # Wait for the LAN and PostgreSQL listener before restoring application networking.
    with socket.create_connection(("192.168.10.65", 5432), timeout=5):
        pass
    info = {service: json.loads(run(["docker", "inspect", name]))[0] for service, (name, _) in SERVICES.items()}
    env = dict(os.environ, API_IMAGE=info["api"]["Config"]["Image"], WEB_IMAGE=info["web"]["Config"]["Image"])
    plans = {service: compose_command(service, item, env) for service, item in info.items()}
    state = Path("/run/aquanotes-bootstrap")
    state.mkdir(mode=0o700, exist_ok=True)
    for service, (_, url) in SERVICES.items():
        marker = state / service
        if not marker.exists() and not healthy(url):
            run(plans[service], env)
            marker.touch()
            print(f"Restored {service} using its existing release and image", flush=True)
    if not all(healthy(url) for _, url in SERVICES.values()):
        raise RuntimeError("Application not ready; retry health checks without repeated recreation")
    print("Aquanotes API and web healthy")


if __name__ == "__main__":
    main()
