#!/usr/bin/env python3
"""Prepare one fresh customer installation; preserve SDK license-init as a separate step."""

import argparse
import json
import os
import platform
import subprocess
import sys
from pathlib import Path

import customer_bundle
import license_artifacts
import license_container
import license_files


def prepare(bundle):
    if sys.platform != "linux":
        raise ValueError("customer preparation must run on the target Linux host")
    license_files.preflight_ids()
    bundle = license_files.safe_path(bundle)
    subprocess.run(["sh", str(bundle / "deployment/scripts/verify-bundle.sh"), str(bundle)],
                   check=True, capture_output=True)
    manifest = license_artifacts.verify_bundle(bundle, imported=True)
    customer_bundle.verify_contents(bundle, manifest)
    native = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64"}.get(
        platform.machine().lower())
    if native != manifest["images"][0]["architecture"]:
        raise ValueError("bundle architecture differs from the native customer host")
    expected = customer_bundle.runtime_config(bundle, manifest)
    env = bundle / "runtime/config/docker.env"
    catalog = bundle / "runtime/config/embedding/docker.json"
    license_files.safe_path(env)
    license_files.safe_path(catalog)
    for path in (env, catalog):
        if path.exists() and (not path.is_file() or path.stat().st_nlink != 1):
            raise ValueError("runtime configuration requires independent regular files")
    if env.exists():
        if customer_bundle.read_env(env) != expected:
            raise ValueError("existing docker.env differs; use the update procedure without overwriting it")
    for index, owner in ((1, (21002, 21002)), (2, (21001, 21001))):
        image = license_container.resolve_image(manifest["images"][index])
        result = subprocess.run([
            "docker", "run", "--rm", "--pull=never", "--network=none", "--read-only",
            "--entrypoint", "sh", image, "-c", "id -u; id -g",
        ], check=True, capture_output=True, text=True)
        if result.stdout.split() != [str(owner[0]), str(owner[1])]:
            raise ValueError("runtime image numeric UID/GID differs from the reviewed layout")
    layout = {
        "runtime": (0, 0, 0o755), "runtime/config": (0, 0, 0o700),
        "runtime/config/embedding": (0, 0, 0o755), "runtime/backups": (0, 0, 0o700),
        **{f"runtime/{name}": (uid, uid, 0o750)
           for uid, names in ((21001, ("data/metor", "logs/docker/metor", "work/metor")),
                              (21002, ("data/ai", "data/ai/documents", "data/ai/chroma",
                                       "logs/docker/ai", "work/ai")))
           for name in names},
    }
    # Validate every existing managed directory before changing anything. Do not
    # recursively repair ownership of existing customer data or follow symlinks.
    for name, (uid, gid, _) in layout.items():
        path = license_files.safe_path(bundle / name)
        if path.exists() and (not path.is_dir() or
                any(path.iterdir()) and name not in {"runtime", "runtime/config", "runtime/config/embedding"}
                and (path.stat().st_uid, path.stat().st_gid) != (uid, gid)):
            raise ValueError("existing nonempty runtime directory has unexpected ownership")
    if catalog.exists():
        data = json.loads(catalog.read_text())
        if data != customer_bundle.EMBEDDING_CATALOG:
            raise ValueError("existing embedding catalog differs; preserve it and use the update procedure")
    for name, (uid, gid, mode) in layout.items():
        path = bundle / name
        path.mkdir(parents=True, exist_ok=True)
        os.chown(path, uid, gid, follow_symlinks=False)
        os.chmod(path, mode)
    if not env.exists():
        customer_bundle.write_env(env, expected)
    os.chown(env, 0, 0, follow_symlinks=False)
    os.chmod(env, 0o600)
    if not catalog.exists():
        with catalog.open("x") as output:
            json.dump(customer_bundle.EMBEDDING_CATALOG, output, ensure_ascii=False, indent=2)
            output.write("\n")
    os.chmod(catalog, 0o644)
    for path in [bundle / customer_bundle.MODEL_PATH,
                 *(bundle / customer_bundle.MODEL_PATH).rglob("*")]:
        os.chmod(path, 0o555 if path.is_dir() else 0o444)
    os.chmod(bundle / customer_bundle.CREDENTIAL_PATH, 0o600)
    print("Runtime configuration and numeric permissions prepared; run license-init separately.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    try:
        prepare(args.root)
    except ValueError as error:
        print(f"Preparation failed: {error}", file=sys.stderr)
        raise SystemExit(1)
    except (OSError, subprocess.CalledProcessError):
        print("Preparation failed: check bundle, imported images, root permissions and existing configuration; "
              "no credentials were printed.", file=sys.stderr)
        raise SystemExit(1)
