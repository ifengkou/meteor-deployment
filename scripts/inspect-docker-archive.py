#!/usr/bin/env python3
"""Inspect and validate a Docker archive using only the Python standard library."""

from __future__ import annotations

import argparse
import hashlib
import json
import tarfile
from pathlib import Path
from typing import Any


def load_json(archive: tarfile.TarFile, name: str) -> Any:
    stream = archive.extractfile(name)
    if stream is None:
        raise RuntimeError(f"archive member is missing: {name}")
    return json.load(stream)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path)
    parser.add_argument("--expect-os", default="linux")
    parser.add_argument("--expect-architecture", default="amd64")
    args = parser.parse_args()

    digest = hashlib.sha256()
    with args.archive.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)

    with tarfile.open(args.archive, "r:*") as archive:
        manifests = load_json(archive, "manifest.json")
        if not isinstance(manifests, list) or len(manifests) != 1:
            raise RuntimeError("expected one image in Docker archive")
        manifest = manifests[0]
        config = load_json(archive, manifest["Config"])
        layers = manifest.get("Layers", [])
        if not layers:
            raise RuntimeError("archive has no image layers")
        for name in [manifest["Config"], *layers]:
            member = archive.getmember(name)
            if not member.isfile():
                raise RuntimeError(f"expected regular archive member: {name}")
            stream = archive.extractfile(member)
            if stream is None:
                raise RuntimeError(f"archive member is missing: {name}")
            member_digest = hashlib.sha256()
            with stream:
                while block := stream.read(1024 * 1024):
                    member_digest.update(block)
            if (
                name.startswith("blobs/sha256/")
                and member_digest.hexdigest() != name.rsplit("/", 1)[1]
            ):
                raise RuntimeError(f"archive blob checksum mismatch: {name}")

    actual_os = config.get("os")
    actual_architecture = config.get("architecture")
    if actual_os != args.expect_os or actual_architecture != args.expect_architecture:
        raise RuntimeError(
            f"unexpected platform: {actual_os}/{actual_architecture}; "
            f"expected {args.expect_os}/{args.expect_architecture}"
        )
    print(
        json.dumps(
            {
                "archive": str(args.archive),
                "bytes": args.archive.stat().st_size,
                "platform": f"{actual_os}/{actual_architecture}",
                "tags": manifest.get("RepoTags", []),
                "layers": len(manifest.get("Layers", [])),
                "sha256": digest.hexdigest(),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
