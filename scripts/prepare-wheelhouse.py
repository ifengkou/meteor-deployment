#!/usr/bin/env python3
"""Stage uv's locked local wheels without changing its exported requirement paths."""

import hashlib
import shutil
import sys
from pathlib import Path


def stage(ai_root, target):
    for line in (target / "requirements-linux.txt").read_text().splitlines():
        requirement = line.strip().removesuffix("\\").strip()
        if not requirement.startswith("./"):
            continue
        relative = Path(requirement)
        if relative.parent != Path("wheelhouse") or relative.suffix != ".whl":
            raise ValueError("local locked requirement must be ./wheelhouse/<wheel>.whl")
        source = ai_root / relative
        destination = target / relative.name
        if not source.is_file() or source.is_symlink():
            raise ValueError(f"locked local wheel is missing: {relative.name}")
        if source.resolve() != destination.resolve():
            shutil.copy2(source, destination)


def checksums(target):
    entries = sorted(p for p in target.iterdir() if p.is_file() and p.name != "SHA256SUMS")
    (target / "SHA256SUMS").write_text("".join(
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n" for path in entries
    ))


if __name__ == "__main__":
    ai_root, target = (Path(value) for value in sys.argv[1:3])
    if sys.argv[3:] == ["--checksums"]:
        checksums(target)
    else:
        stage(ai_root, target)
