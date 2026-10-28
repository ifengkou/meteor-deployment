#!/usr/bin/env python3
"""Run existing stack tools as Linux root on this Mac's Docker Desktop daemon."""

import argparse
import json
import re
import socket
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import customer_bundle

WORKSPACE = Path(__file__).resolve().parents[2]
TOOLS_IMAGE = "icp-diag-local-tools:py312-docker2751"
CONTEXT = "desktop-linux"


def license_volume_mount(config, record, project):
    name = config.get("DESKTOP_LICENSE_VOLUME")
    mountpoint = record.get("Mountpoint", "")
    if (name != project + "-license" or record.get("Name") != name
            or record.get("Driver") != "local" or record.get("Options")
            or not Path(mountpoint).is_absolute()
            or Path(mountpoint).parts[-3:] != ("volumes", name, "_data")
            or config.get("LICENSE_ROOT") != mountpoint):
        raise ValueError("use this project's plain local license volume and its exact Mountpoint as LICENSE_ROOT")
    return f"type=volume,src={name},dst={mountpoint}"


def tool_command(workspace, image, arguments, license_mount=None):
    """Keep paths identical in the client, maintenance container and daemon."""
    if re.fullmatch(r"sha256:[0-9a-f]{64}", image) is None:
        raise ValueError("maintenance image must resolve to an immutable local ID")
    command = [
        "docker", "--context", CONTEXT, "run", "--rm", "--pull=never",
        "--network=none", "--read-only", "--user", "0:0",
        "--security-opt", "no-new-privileges:true", "--tmpfs", "/tmp",
        "--mount", f"type=bind,src={workspace},dst={workspace}",
        "--mount", "type=bind,src=/var/run/docker.sock,dst=/var/run/docker.sock",
    ]
    if license_mount:
        command += ["--mount", license_mount]
    return command + ["--workdir", str(workspace), "--entrypoint", "", image] + list(arguments)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tools-image", default=TOOLS_IMAGE)
    parser.add_argument("--project", default="icp-diag-local")
    parser.add_argument("--env-file", type=Path, default=WORKSPACE / "runtime/config/docker.env")
    parser.add_argument("command", choices=("compose", "license-init", "backup", "restore-stack", "license-recovery", "tool"))
    parser.add_argument("arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if sys.platform != "darwin":
        raise ValueError("this wrapper is only for macOS Docker Desktop; Linux uses local-stack.py")
    if not all((WORKSPACE / name / "Dockerfile").is_file()
               for name in ("ai-runtime-service", "metor-service", "frontend")):
        raise ValueError("a source workspace is required; do not use this wrapper in customer bundles")
    env_file = args.env_file.resolve()
    if WORKSPACE not in env_file.parents:
        raise ValueError("the runtime env must be inside this mounted workspace")
    # The Linux container cannot detect native Mac writers on its own localhost.
    if args.command in ("license-init", "backup", "restore-stack", "tool"):
        for port in (8080, 8090):
            with socket.socket() as probe:
                probe.settimeout(1)
                if probe.connect_ex(("127.0.0.1", port)) == 0:
                    raise ValueError(f"stop the native Mac service on {port} before maintenance")
    image = json.loads(subprocess.check_output(
        ["docker", "--context", CONTEXT, "image", "inspect", args.tools_image], text=True,
    ))[0]
    if image["Os"] != "linux":
        raise ValueError("Linux maintenance image required")
    config = customer_bundle.read_env(env_file) if env_file.is_file() else {}
    license_mount = None
    if config.get("DESKTOP_LICENSE_VOLUME"):
        record = json.loads(subprocess.check_output(
            ["docker", "--context", CONTEXT, "volume", "inspect", config["DESKTOP_LICENSE_VOLUME"]],
            text=True,
        ))[0]
        license_mount = license_volume_mount(config, record, args.project)
    if args.command == "tool":
        if not args.arguments:
            parser.error("tool requires a Linux command")
        arguments = args.arguments
    else:
        arguments = ["python3", str(WORKSPACE / "deployment/scripts/local-stack.py"),
                     "--project", args.project, "--env-file", str(env_file),
                     args.command] + args.arguments
    subprocess.run(tool_command(WORKSPACE, image["Id"], arguments, license_mount), check=True)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, subprocess.CalledProcessError) as error:
        print(f"Docker Desktop operation failed: {error}", file=sys.stderr)
        sys.exit(1)
