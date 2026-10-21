"""Standard-library-only offline license initialization, independent of application SDKs.

Only this installer creates identity and clock seeds. Applications must never recreate them.
"""

import base64
import fcntl
import grp
import hashlib
import hmac
import json
import os
import pwd
import re
import secrets
import stat
import tempfile
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

PRODUCT = "icp-diag"
READ_GID = 21000
SERVICE_IDS = {"metor": (21001, 21001), "ai": (21002, 21002)}
MAX_BYTES = 65536
MAX_CLOCK_BYTES = 8192
MAX_CLOCK_PAYLOAD_BYTES = 4096


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def _nonstandard(value):
    raise ValueError("nonstandard JSON number")


def strict_object(content):
    if not isinstance(content, bytes) or not 0 < len(content) <= MAX_BYTES:
        raise ValueError("invalid JSON size")
    try:
        result = json.loads(content.decode("utf-8"), object_pairs_hook=_pairs,
                            parse_constant=_nonstandard)
    except (UnicodeError, ValueError, RecursionError) as error:
        raise ValueError("invalid UTF-8 JSON") from error
    if not isinstance(result, dict):
        raise ValueError("JSON object required")
    return result


def read_regular(path, maximum=MAX_BYTES):
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                 | getattr(os, "O_NONBLOCK", 0))
    with os.fdopen(fd, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError("regular file required")
        content = stream.read(maximum + 1)
    if len(content) > maximum:
        raise ValueError("file exceeds size limit")
    return content


def _uuid(value):
    if not isinstance(value, str):
        raise ValueError("canonical UUIDv4 required")
    parsed = uuid.UUID(value)
    if str(parsed) != value or parsed.version != 4:
        raise ValueError("canonical UUIDv4 required")
    return value


def parse_installation(content):
    data = strict_object(content)
    if (set(data) != {"schema_version", "product_id", "installation_id", "initialized"}
            or type(data["schema_version"]) is not int or data["schema_version"] != 1
            or data["product_id"] != PRODUCT or type(data["initialized"]) is not bool):
        raise ValueError("invalid installation identity")
    _uuid(data["installation_id"])
    return data


def _utc(value):
    if not isinstance(value, str) or re.fullmatch(
        r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z", value
    ) is None:
        raise ValueError("exact UTC second timestamp required")
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def _b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(value):
    if not isinstance(value, str) or not value or re.fullmatch(r"[A-Za-z0-9_-]+", value) is None:
        raise ValueError("invalid Base64URL")
    raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    if _b64(raw) != value:
        raise ValueError("noncanonical Base64URL")
    return raw


def seed_clock(installation_id, service_key, service, now):
    _uuid(installation_id)
    if len(service_key) != 32 or service not in SERVICE_IDS:
        raise ValueError("invalid seed context")
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("aware UTC clock required")
    payload = canonical({
        "schema_version": 1, "product_id": PRODUCT, "installation_id": installation_id,
        "service": service, "epoch": 0, "sequence": 0,
        "high_watermark": now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "last_recovery_id": None,
    })
    key = hmac.digest(service_key, f"{PRODUCT}/state/{service}/v1".encode("ascii"), "sha256")
    return canonical({"payload": _b64(payload), "mac": _b64(hmac.digest(key, payload, "sha256"))})


def validate_clock(content, installation_id, service_key, service):
    if len(content) > MAX_CLOCK_BYTES or len(service_key) != 32:
        raise ValueError("invalid clock size or key")
    outer = strict_object(content)
    if set(outer) != {"payload", "mac"}:
        raise ValueError("invalid clock envelope")
    payload, mac = _unb64(outer["payload"]), _unb64(outer["mac"])
    key = hmac.digest(service_key, f"{PRODUCT}/state/{service}/v1".encode("ascii"), "sha256")
    if len(mac) != 32 or not hmac.compare_digest(mac, hmac.digest(key, payload, "sha256")):
        raise ValueError("clock integrity failure")
    if len(payload) > MAX_CLOCK_PAYLOAD_BYTES:
        raise ValueError("clock payload exceeds limit")
    data = strict_object(payload)
    if (set(data) != {"schema_version", "product_id", "installation_id", "service", "epoch",
                     "sequence", "high_watermark", "last_recovery_id"}
            or type(data["schema_version"]) is not int or data["schema_version"] != 1
            or data["product_id"] != PRODUCT or data["installation_id"] != installation_id
            or data["service"] != service):
        raise ValueError("clock context mismatch")
    for name in ("epoch", "sequence"):
        if type(data[name]) is not int or not 0 <= data[name] <= 2**63 - 1:
            raise ValueError("invalid clock sequence")
    _utc(data["high_watermark"])
    recovery_id = data["last_recovery_id"]
    if recovery_id is not None:
        if not isinstance(recovery_id, str) or str(uuid.UUID(recovery_id)) != recovery_id:
            raise ValueError("invalid recovery reference")
    return data


def _safe_path(path):
    absolute = Path(path).absolute()
    if any(part.is_symlink() for part in (absolute, *absolute.parents)):
        raise ValueError("license paths must not pass through symbolic links")
    return absolute


def _sync_directory(path):
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write(path, content, uid, gid, mode, ownership, *, exclusive=False):
    fd, name = tempfile.mkstemp(prefix=".license-init-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as target:
            os.fchmod(target.fileno(), mode)
            ownership(Path(name), uid, gid)
            target.write(content)
            target.flush()
            os.fsync(target.fileno())
        if exclusive:
            os.link(name, path)
            os.unlink(name)
        else:
            os.replace(name, path)
        _sync_directory(path.parent)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def _ownership(path, uid, gid):
    os.chown(path, uid, gid, follow_symlinks=False)


def preflight_ids():
    if os.geteuid() != 0:
        raise ValueError("license-init requires root to assign reviewed numeric ownership")
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


def _check_owners(path, uid, gid, mode, ownership):
    info = path.lstat()
    if stat.S_IMODE(info.st_mode) != mode:
        raise ValueError(f"license path has incorrect mode: {path.name}")
    if ownership is _ownership and (info.st_uid, info.st_gid) != (uid, gid):
        raise ValueError(f"license path has incorrect ownership: {path.name}")


@contextmanager
def _init_lock(root):
    fd = os.open(root / ".init.lock", os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def initialize_license(root, *, now=None, ownership=_ownership, id_factory=uuid.uuid4,
                       key_factory=lambda: secrets.token_bytes(32), failpoint=lambda point: None):
    """Create/resume only a draft installation; completed installations are read-only checked.

    Injectable providers are for isolated unit tests, never exposed as customer CLI switches.
    """
    root = _safe_path(root)
    if ownership is _ownership:
        preflight_ids()
    root.mkdir(mode=0o750, parents=True, exist_ok=True)
    if not root.is_dir():
        raise ValueError("license root must be a directory")
    with _init_lock(root):
        identity = root / "identity"
        shared = root / "shared"
        state = root / "state"
        installation = identity / "installation.json"
        key_path = identity / "service.key"
        for path in (identity, shared, state, state / "metor", state / "ai"):
            _safe_path(path)
        directories = ((root, 0, READ_GID, 0o750), (identity, 0, READ_GID, 0o750),
                       (shared, 21001, READ_GID, 0o750), (state, 0, READ_GID, 0o750),
                       (state / "metor", 21001, 21001, 0o700),
                       (state / "ai", 21002, 21002, 0o700))
        stages = sorted(root.glob(".identity-stage-*"))
        if stages and not installation.exists():
            if len(stages) != 1:
                raise ValueError("multiple interrupted identity stages; inspect manually")
            stage = _safe_path(stages[0])
            staged_identity = parse_installation(read_regular(stage / "installation.json"))
            staged_key = read_regular(stage / "service.key", 32)
            if staged_identity["initialized"] or len(staged_key) != 32:
                raise ValueError("incomplete identity stage; inspect manually")
            if identity.exists():
                identity.rmdir()  # only an empty unpublished target may be replaced
            os.rename(stage, identity)
            _sync_directory(root)
        if installation.exists() or installation.is_symlink():
            data = parse_installation(read_regular(installation))
            key = read_regular(key_path, 32)
            if len(key) != 32:
                raise ValueError("existing installation key is missing or invalid; restore backup")
            if data["initialized"]:
                for path, uid, gid, mode in directories:
                    _check_owners(path, uid, gid, mode, ownership)
                for path in (installation, key_path):
                    _check_owners(path, 0, READ_GID, 0o640, ownership)
                for service, (uid, gid) in SERVICE_IDS.items():
                    path = state / service / "clock.json"
                    validate_clock(read_regular(path), data["installation_id"], key, service)
                    _check_owners(path, uid, gid, 0o600, ownership)
                return {"installation_id": data["installation_id"], "state": "ALREADY_INITIALIZED"}
        else:
            # Do not adopt orphan keys/states or arbitrary pre-existing files.
            if any(path.exists() and any(path.iterdir()) for path in (identity, shared, state)):
                raise ValueError("orphan license data without installation identity; inspect manually")
            for path, uid, gid, mode in directories:
                if path == identity:
                    continue
                path.mkdir(mode=mode, exist_ok=True)
                ownership(path, uid, gid)
                os.chmod(path, mode)
            data = {"schema_version": 1, "product_id": PRODUCT,
                    "installation_id": str(id_factory()), "initialized": False}
            _uuid(data["installation_id"])
            key = key_factory()
            if len(key) != 32:
                raise ValueError("key provider must return 32 bytes")
            stage = Path(tempfile.mkdtemp(prefix=".identity-stage-", dir=root))
            ownership(stage, 0, READ_GID)
            os.chmod(stage, 0o750)
            _write(stage / "installation.json", canonical(data), 0, READ_GID, 0o640,
                   ownership, exclusive=True)
            _write(stage / "service.key", key, 0, READ_GID, 0o640,
                   ownership, exclusive=True)
            _sync_directory(stage)
            if identity.exists():
                identity.rmdir()
            os.rename(stage, identity)
            _sync_directory(root)
            # Publish the draft and its matching key as one directory operation,
            # so a published draft never precedes its durable key.
            failpoint("draft_written")
            failpoint("key_written")
        for path, uid, gid, mode in directories:
            path.mkdir(mode=mode, exist_ok=True)
            ownership(path, uid, gid)
            os.chmod(path, mode)
        instant = now or datetime.now(timezone.utc)
        for service, (uid, gid) in SERVICE_IDS.items():
            path = state / service / "clock.json"
            if path.exists() or path.is_symlink():
                validate_clock(read_regular(path), data["installation_id"], key, service)
            else:
                _write(path, seed_clock(data["installation_id"], key, service, instant),
                       uid, gid, 0o600, ownership, exclusive=True)
            failpoint(f"{service}_seed_written")
        for path, _, _, _ in reversed(directories):
            _sync_directory(path)
        data["initialized"] = True
        _write(installation, canonical(data), 0, READ_GID, 0o640, ownership)
        failpoint("completed")
        return {"installation_id": data["installation_id"], "state": "INITIALIZED"}
