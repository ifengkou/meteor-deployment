"""Private same-host licensing backup; never initializes or replaces an installation."""

import hashlib
import io
import os
import shutil
import tarfile
import tempfile
from pathlib import Path

import license_files as layout

ARCHIVE = "license-state.tar.gz"
DIRECTORIES, FILES, REQUIRED = layout.DIRECTORIES, layout.FILES, layout.REQUIRED


def configured_path(config, key, default, base):
    value = os.environ.get(key, config.get(key)) or default
    if "$" in value:
        raise ValueError(f"{key} must use a literal path, without variable interpolation")
    path = Path(value)
    return path if path.is_absolute() else base / path


def license_root(config, base):
    # Compose resolves bind sources against its first compose file, not the shell cwd.
    return layout.safe_path(configured_path(config, "LICENSE_ROOT", "../runtime/license", base))


def host_fingerprint(config, base):
    path = configured_path(config, "LICENSE_MACHINE_ID_PATH", "/etc/machine-id", base)
    if not path.is_file():
        return None
    try:
        value = layout.read_regular(path, 4096).strip()
    except (OSError, ValueError):
        return None
    return hashlib.sha256(value).hexdigest() if value else None


def read_installation(root):
    paths = layout.validate_layout(root)
    return {name: layout.read_regular(paths[name]) for name in FILES.keys() & paths.keys()}


def preflight(root):
    # Called before writers stop: filesystem preflight only, never protocol verification.
    layout.preflight_ids()
    layout.validate_layout(root)


def backup(root, archive, machine_fingerprint, check):
    contents = read_installation(root)
    installation = check(root)
    if contents != read_installation(root):
        raise ValueError("license files changed during stopped backup; stop all writers")
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
                    or item.pax_headers or item.size > layout.MAX_BYTES):
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
                contents[name] = source.extractfile(item).read(layout.MAX_BYTES + 1)
    if directories != set(DIRECTORIES):
        raise ValueError("license archive is missing directories")
    if not REQUIRED.issubset(contents):
        raise ValueError("license backup is missing identity/key/clock")
    if (not isinstance(metadata, dict)
            or set(metadata) != {"archive", "installationId", "machineIdSha256"}
            or metadata["archive"] != ARCHIVE
            or not isinstance(metadata["installationId"], str)):
        raise ValueError("license backup manifest does not match installation")
    return contents


def prepare_restore(root, archive, metadata, machine_fingerprint, check):
    layout.preflight_ids()
    layout.safe_path(root)
    if archive is None:
        # Legacy business backups must preserve a complete existing licensing installation.
        read_installation(root)
        check(root)
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
        if check(stage) != metadata["installationId"]:
            raise ValueError("license backup manifest does not match installation")
        for name in reversed(DIRECTORIES):
            layout.sync_directory(stage / name)
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
    layout.sync_directory(root.parent)
