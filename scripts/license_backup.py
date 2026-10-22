"""Private same-host licensing backup; never initializes or replaces an installation."""

import hashlib
import io
import os
import shutil
import stat
import tarfile
import tempfile
from pathlib import Path

import license_init as installer

ARCHIVE = "license-state.tar.gz"
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
REQUIRED = {"identity/installation.json", "identity/service.key",
            "state/metor/clock.json", "state/ai/clock.json"}


def configured_path(config, key, default, base):
    value = os.environ.get(key, config.get(key)) or default
    if "$" in value:
        raise ValueError(f"{key} must use a literal path, without variable interpolation")
    path = Path(value)
    return path if path.is_absolute() else base / path


def license_root(config, base):
    # Compose resolves bind sources against its first compose file, not the shell cwd.
    return installer._safe_path(configured_path(config, "LICENSE_ROOT", "../runtime/license", base))


def host_fingerprint(config, base):
    path = configured_path(config, "LICENSE_MACHINE_ID_PATH", "/etc/machine-id", base)
    if not path.is_file():
        return None
    try:
        value = installer.read_regular(path, 4096).strip()
    except (OSError, ValueError):
        return None
    return hashlib.sha256(value).hexdigest() if value else None


def check_metadata(info, expected):
    if (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)) != expected:
        raise ValueError("license path has unreviewed numeric owner or permissions")


def validate_contents(contents):
    if not REQUIRED.issubset(contents):
        raise ValueError("license backup is missing identity/key/clock; do not run license-init")
    data = installer.parse_installation(contents["identity/installation.json"])
    key = contents["identity/service.key"]
    if not data["initialized"] or len(key) != 32:
        raise ValueError("license identity is incomplete; restore or inspect it manually")
    for service in ("metor", "ai"):
        installer.validate_clock(contents[f"state/{service}/clock.json"],
                                 data["installation_id"], key, service)
    return data["installation_id"]


def read_installation(root):
    installer._safe_path(root)
    if not root.is_dir():
        raise ValueError("license directory is missing; do not regenerate identity during backup")
    contents = {}
    for name, expected in DIRECTORIES.items():
        path = root / name
        if not stat.S_ISDIR(path.lstat().st_mode):
            raise ValueError("license directories must not be links or special files")
        check_metadata(path.lstat(), expected)
    for path in root.rglob("*"):
        relative = path.relative_to(root).as_posix()
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode):
            raise ValueError("license backup refuses symbolic links")
        if path.name.endswith(".lock") or path.name.startswith("."):
            continue
        if relative in DIRECTORIES:
            continue
        if relative not in FILES or not stat.S_ISREG(info.st_mode):
            raise ValueError("unexpected file in license directory")
        check_metadata(info, FILES[relative])
        contents[relative] = installer.read_regular(path)
    return contents, validate_contents(contents)


def preflight(root):
    installer.preflight_ids()
    return read_installation(root)


def backup(root, archive, machine_fingerprint):
    contents, installation = read_installation(root)
    # The enclosing backup directory is private; do not leave the archive public on error.
    fd = os.open(archive, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "wb") as output, tarfile.open(fileobj=output, mode="w:gz") as target:
        for name, (uid, gid, mode) in {**DIRECTORIES, **FILES}.items():
            if name not in DIRECTORIES and name not in contents:
                continue
            item = tarfile.TarInfo(name)
            item.uid, item.gid, item.mode = uid, gid, mode
            if name in DIRECTORIES:
                item.type = tarfile.DIRTYPE
                target.addfile(item)
            else:
                item.size = len(contents[name])
                target.addfile(item, io.BytesIO(contents[name]))
    return {"archive": ARCHIVE, "installationId": installation,
            "machineIdSha256": machine_fingerprint}


def validate_archive(archive, metadata):
    contents, directories, seen = {}, set(), set()
    with tarfile.open(archive) as source:
        for item in source:
            name = item.name
            if (name in seen or name not in {**DIRECTORIES, **FILES}
                    or item.pax_headers or item.size > installer.MAX_BYTES):
                raise ValueError("unsafe or unexpected license archive entry")
            seen.add(name)
            expected = DIRECTORIES.get(name) or FILES.get(name)
            if (item.uid, item.gid, item.mode) != expected:
                raise ValueError("license archive has unreviewed numeric owner or permissions")
            if name in DIRECTORIES:
                if not item.isdir():
                    raise ValueError("license archive directory required")
                directories.add(name)
            else:
                if not item.isfile():
                    raise ValueError("license archive refuses links and special files")
                contents[name] = source.extractfile(item).read(installer.MAX_BYTES + 1)
    if directories != set(DIRECTORIES):
        raise ValueError("license archive is missing directories")
    installation = validate_contents(contents)
    if (not isinstance(metadata, dict)
            or set(metadata) != {"archive", "installationId", "machineIdSha256"}
            or metadata["archive"] != ARCHIVE or metadata["installationId"] != installation):
        raise ValueError("license backup manifest does not match installation")
    return contents


def prepare_restore(root, archive, metadata, machine_fingerprint):
    installer.preflight_ids()
    installer._safe_path(root)
    if archive is None:
        # Legacy business backups must preserve a complete existing licensing installation.
        read_installation(root)
        return None
    contents = validate_archive(archive, metadata)
    if (not machine_fingerprint or metadata.get("machineIdSha256") != machine_fingerprint):
        raise ValueError("license restore requires the same readable host machine-id; reissue on a new host")
    if root.exists() and (not root.is_dir() or any(root.iterdir())):
        raise ValueError("license restore refuses a nonempty target, including another installation")
    parent = root.parent
    if not parent.is_dir() or not os.access(parent, os.W_OK | os.X_OK):
        raise ValueError("license restore parent must exist and be writable")
    stage = Path(tempfile.mkdtemp(prefix=".license-restore-", dir=parent))
    try:
        for name, (uid, gid, mode) in DIRECTORIES.items():
            path = stage / name
            path.mkdir(exist_ok=True)
            os.chown(path, uid, gid)
            os.chmod(path, mode)
        for name, content in contents.items():
            path = stage / name
            with path.open("xb") as target:
                os.fchmod(target.fileno(), FILES[name][2])
                os.fchown(target.fileno(), *FILES[name][:2])
                target.write(content)
                target.flush()
                os.fsync(target.fileno())
        read_installation(stage)
        for name in reversed(DIRECTORIES):
            installer._sync_directory(stage / name)
        return stage
    except BaseException:
        shutil.rmtree(stage)
        raise


def publish_restore(root, stage):
    if stage is None:
        return
    if root.exists():
        root.rmdir()  # Fail if anything appeared after preflight; never overwrite an installation.
    os.rename(stage, root)
    installer._sync_directory(root.parent)
