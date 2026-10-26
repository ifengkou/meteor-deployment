"""Reviewed ICP filesystem layout. No licensing protocol or identity generation."""

import grp
import os
import pwd
import stat
from pathlib import Path

MAX_BYTES = 65536
DIRECTORIES = {
    ".": (0, 21000, 0o750), "identity": (0, 21000, 0o750),
    "shared": (21001, 21000, 0o750), "state": (0, 21000, 0o750),
    "state/metor": (21001, 21001, 0o700), "state/ai": (21002, 21002, 0o700),
}
FILES = {
    "identity/installation.json": (0, 21000, 0o640),
    "identity/service.key": (0, 21000, 0o640),
    "shared/active.license.json": (21001, 21000, 0o640),
    **{f"state/{service}/{name}": (uid, uid, 0o600)
       for service, uid in (("metor", 21001), ("ai", 21002))
       for name in ("clock.json", "recovery-challenge.json")},
}
LOCKS = {".init.lock", "shared/license-import.lock",
         "state/metor/clock.lock", "state/ai/clock.lock",
         "state/metor/clock.json.lock"}
REQUIRED = {"identity/installation.json", "identity/service.key",
            "state/metor/clock.json", "state/ai/clock.json"}


def safe_path(path):
    absolute = Path(os.path.abspath(path))
    if any(part.is_symlink() for part in (absolute, *absolute.parents)):
        raise ValueError("license paths must not pass through symbolic links")
    return absolute


def read_regular(path, maximum=MAX_BYTES):
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                 | getattr(os, "O_NONBLOCK", 0))
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError("single regular file required")
        content = stream.read(maximum + 1)
    if len(content) > maximum:
        raise ValueError("file exceeds size limit")
    return content


def sync_directory(path):
    safe_path(path)
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
                 | getattr(os, "O_NOFOLLOW", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def preflight_ids():
    """Run on the host as well as using root inside the maintenance container."""
    if os.geteuid() != 0:
        raise ValueError("license maintenance requires root for reviewed numeric ownership")
    for uid, name in ((21001, "metor"), (21002, "ai-runtime")):
        try:
            if pwd.getpwuid(uid).pw_name != name:
                raise ValueError(f"UID {uid} is already used by another host account")
        except KeyError:
            pass
    for gid, name in ((21000, "license-runtime"), (21001, "metor"), (21002, "ai-runtime")):
        try:
            if grp.getgrgid(gid).gr_name != name:
                raise ValueError(f"GID {gid} is already used by another host group")
        except KeyError:
            pass


def check_metadata(info, expected):
    if (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)) != expected:
        raise ValueError("license path has unreviewed numeric owner or permissions")


def reviewed_paths(root, *, draft=False):
    """Reject links/special/unknown paths, including temporary files, before any write."""
    root = safe_path(root)
    if not root.is_dir():
        raise ValueError("license directory is missing; do not regenerate identity during backup")
    result = {}
    for path in root.rglob("*"):
        name = path.relative_to(root).as_posix()
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode):
            raise ValueError("license files refuse symbolic links")
        if name in DIRECTORIES:
            if not stat.S_ISDIR(info.st_mode):
                raise ValueError("license directory required")
        elif draft and name == ".identity-stage":
            if not stat.S_ISDIR(info.st_mode):
                raise ValueError("SDK draft directory required")
        elif draft and name in {".identity-stage/installation.json", ".identity-stage/service.key"}:
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ValueError("single SDK draft file required")
        elif name in FILES or name in LOCKS:
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ValueError("single regular license file required")
        else:
            raise ValueError("unexpected file in license directory")
        result[name] = path
    return result


def validate_layout(root):
    paths = reviewed_paths(root)
    if not REQUIRED.issubset(paths):
        raise ValueError("license backup is missing identity/key/clock; do not run license-init")
    for name, expected in DIRECTORIES.items():
        path = root / name
        if not stat.S_ISDIR(path.lstat().st_mode):
            raise ValueError("license directory required")
        check_metadata(path.lstat(), expected)
    for name in FILES.keys() & paths.keys():
        check_metadata(paths[name].lstat(), FILES[name])
    return paths


def apply_permissions(root):
    """Only chmod/chown the explicit layout after SDK initialization succeeds."""
    paths = reviewed_paths(root)
    if not REQUIRED.issubset(paths):
        raise ValueError("SDK initialization did not produce the complete installation")
    for name, (uid, gid, mode) in {**DIRECTORIES, **FILES}.items():
        path = root / name
        if name in DIRECTORIES or name in paths:
            os.chown(path, uid, gid, follow_symlinks=False)
            os.chmod(path, mode, follow_symlinks=False)
            if name not in DIRECTORIES:
                fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
    validate_layout(root)
    for name in reversed(DIRECTORIES):
        sync_directory(root / name)
