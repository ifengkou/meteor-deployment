"""Narrow, offline adapter to the SDK already installed in a fixed AI image."""

import json
import os
import re
import subprocess

import license_files

IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}")


def fixed_image(config, deployment):
    manifest_path = deployment.parent / "manifest.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text())
        image = manifest.get("licenseToolsImage")
        if image not in {entry.get("id") for entry in manifest.get("images", [])}:
            raise ValueError("bundle licenseToolsImage must reference a packaged image ID")
    else:
        image = os.environ.get("LICENSE_TOOLS_IMAGE", config.get("LICENSE_TOOLS_IMAGE", ""))
    if not isinstance(image, str) or IMAGE_ID.fullmatch(image) is None:
        raise ValueError("LICENSE_TOOLS_IMAGE must be the reviewed local SDK 0.7.1 AI image sha256 ID")
    record = json.loads(subprocess.run(
        ["docker", "image", "inspect", image], check=True, capture_output=True, text=True,
    ).stdout)
    if len(record) != 1 or record[0]["Id"] != image or record[0]["Os"] != "linux":
        raise ValueError("license tools image is unavailable or does not match its fixed Linux ID")
    return image


class LicenseTools:
    def __init__(self, config, deployment):
        self.deployment = deployment
        self.image = fixed_image(config, deployment)
        # Probe the actual interpreter/config before creating or modifying the target root.
        self.probe = self.operation("probe")

    def operation(self, action, root=None):
        scripts = license_files.safe_path(self.deployment / "scripts")
        command = ["docker", "run", "--rm", "--pull=never", "--network=none",
                   "--read-only", "--user", "0:0", "--security-opt", "no-new-privileges:true",
                   "--mount", f"type=bind,src={scripts},dst=/opt/license-tools,readonly",
                   "--env", "PYTHONPATH=/app", "--entrypoint", "/app/.venv/bin/python"]
        if root is not None:
            root = license_files.safe_path(root)
            if root == scripts or root in scripts.parents or scripts in root.parents:
                raise ValueError("license tools must be mounted outside the authorization directory")
            command += ["--mount", f"type=bind,src={root},dst=/run/icp-license"
                        + (",readonly" if action == "check" else "")]
        command += [self.image, "/opt/license-tools/license_init.py", action]
        if root is not None:
            command += ["--root", "/run/icp-license"]
        try:
            result = subprocess.run(command, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as error:
            detail = error.stderr or "check the fixed local image and preserved installation"
            raise ValueError("license SDK tool failed: " + detail.strip()[:1000]) from error
        try:
            data = json.loads(result.stdout)
        except (ValueError, TypeError) as error:
            raise ValueError("license tools returned an invalid response") from error
        if not isinstance(data, dict):
            raise ValueError("license tools returned an invalid response")
        return data

    def initialize(self, root):
        license_files.preflight_ids()
        root = license_files.safe_path(root)
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        return self.operation("init", root)

    def check(self, root):
        result = self.operation("check", root)
        if result.get("state") != "VALID" or not isinstance(result.get("installation_id"), str):
            raise ValueError("SDK installation validation did not complete")
        return result["installation_id"]
