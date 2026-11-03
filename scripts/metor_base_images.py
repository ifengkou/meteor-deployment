#!/usr/bin/env python3
"""Keep platform-specific Metor bases in the current Docker daemon's image store."""

import argparse
import hashlib
import json
import os
import subprocess


DEFAULTS = {
    "METOR_JDK_IMAGE": "eclipse-temurin:21-jdk-jammy",
    "METOR_JRE_IMAGE": "eclipse-temurin:21-jre-jammy",
}


def inspect_image(reference, platform):
    # --platform selects a child manifest in the containerd store. Older Docker
    # versions can inspect only the single image attached to a tag.
    for selection in (["--platform", platform], []):
        result = subprocess.run(
            ["docker", "image", "inspect", *selection, "--format",
             "{{.Id}} {{.Os}}/{{.Architecture}}", reference],
            capture_output=True, text=True,
        )
        fields = result.stdout.split()
        # An index may list a platform whose config/layers have not been pulled.
        if result.returncode == 0 and len(fields) == 2 and fields[1] == platform:
            return fields[0]
    return None


def cache_reference(key, source, architecture):
    version = DEFAULTS[key].split(":", 1)[1]
    suffix = "" if source == DEFAULTS[key] else "-" + hashlib.sha256(source.encode()).hexdigest()[:12]
    return f"icp-diag-base/eclipse-temurin:{version}{suffix}-{architecture}"


def pinned_reference(reference):
    # A tag alone can still trigger remote resolution for a non-native platform.
    result = subprocess.run(
        ["docker", "image", "inspect", "--format", "{{json .RepoDigests}}", reference],
        check=True, capture_output=True, text=True,
    )
    digests = json.loads(result.stdout) or []
    repository = reference.rsplit(":", 1)[0]
    matching = [item for item in digests if item.startswith(repository + "@")]
    if matching or digests:
        return reference + "@" + (matching or digests)[0].split("@", 1)[1]
    # Classic stores may have no repository digest for locally built images.
    return reference


def prepare(platform, refresh=False):
    if platform not in ("linux/arm64", "linux/amd64"):
        raise ValueError("Metor base cache supports linux/arm64 and linux/amd64")
    architecture = platform.split("/")[1]
    bases = {}
    for key, default in DEFAULTS.items():
        source = os.environ.get(key) or default
        candidates = [source]
        if source == default:
            # An explicit registry host bypasses a broken docker.io mirror.
            candidates.append(f"registry-1.docker.io/library/{source}")
        cached = cache_reference(key, source, architecture)
        image_id = inspect_image(cached, platform)
        if image_id and not refresh:
            print(f"Using cached base: {cached} ({platform})", flush=True)
            bases[key] = cached
            continue

        # Protect both available variants before moving a shared upstream tag.
        for arch in ("arm64", "amd64"):
            saved = cache_reference(key, source, arch)
            if inspect_image(saved, f"linux/{arch}"):
                continue
            for candidate in candidates:
                existing = inspect_image(candidate, f"linux/{arch}")
                if existing:
                    subprocess.run(["docker", "image", "tag", existing, saved], check=True)
                    break
        image_id = inspect_image(cached, platform)
        if not image_id or refresh:
            for candidate in candidates:
                result = subprocess.run(["docker", "pull", "--platform", platform, candidate])
                if result.returncode == 0:
                    image_id = inspect_image(candidate, platform)
                    if image_id:
                        break
            else:
                raise ValueError(f"cannot prepare {source} for {platform}; set {key} to an accessible image")
            subprocess.run(["docker", "image", "tag", image_id, cached], check=True)
        print(f"Prepared base: {cached} ({platform})", flush=True)
        bases[key] = cached
    return bases


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", required=True, choices=("linux/arm64", "linux/amd64"))
    parser.add_argument("--refresh", action="store_true", help="explicitly pull updated bases for this platform")
    args = parser.parse_args()
    prepare(args.platform, refresh=args.refresh)
