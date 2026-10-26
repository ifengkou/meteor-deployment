"""Synthetic fixture operations inside a Linux volume; never shipped as installer."""

import hashlib
import importlib.util
import json
import os
import shutil
import stat
import sys
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

root = Path(os.environ.get("LICENSE_PROBE_ROOT", "/fixtures")) / sys.argv[2]
action = sys.argv[1]
if action == "permissions":
    root = Path("/license")
if action == "paths":
    print(json.dumps({"paths": sorted(str(path.relative_to(root)) for path in root.rglob("*"))}))
elif action == "init":
    spec = importlib.util.spec_from_file_location("old_initializer", "/probe/baseline-initializer.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    print(json.dumps(module.initialize_license(root)))
elif action == "copy":
    shutil.copytree(Path("/fixtures") / sys.argv[3], root)
    for path in [root, *root.rglob("*")]:
        source = Path("/fixtures") / sys.argv[3] / path.relative_to(root)
        info = source.stat()
        os.chown(path, info.st_uid, info.st_gid)
        os.chmod(path, stat.S_IMODE(info.st_mode))
    print("{}")
elif action == "snapshot":
    result = {}
    for path in [root, *sorted(root.rglob("*"))]:
        if path.name.endswith(".lock"):
            continue
        info = path.stat()
        result[str(path.relative_to(root))] = {
            "uid": info.st_uid, "gid": info.st_gid, "mode": stat.S_IMODE(info.st_mode),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None,
        }
    print(json.dumps(result))
elif action == "commercial":
    target = root / "shared/active.license.json"
    if sys.argv[3] == "NONE":
        target.unlink(missing_ok=True)
    else:
        target.write_bytes(Path(sys.argv[3]).read_bytes())
        os.chown(target, 21001, 21000)
        target.chmod(0o640)
    print("{}")
elif action in ("rollback", "broken", "missing", "clock"):
    from license_sdk.runtime import decode_clock, encode_clock
    service = sys.argv[3]
    target = root / "state" / service / "clock.json"
    context = dict(product_id="icp-diag", installation_id=json.loads((root / "identity/installation.json").read_bytes())["installation_id"],
                   service=service, service_key=(root / "identity/service.key").read_bytes())
    state = decode_clock(target.read_bytes(), **context)
    if action == "missing":
        target.unlink()
        print("{}")
    elif action == "clock":
        print(json.dumps({"epoch": state.epoch, "sequence": state.sequence, "high_watermark": str(state.high_watermark)}))
    else:
        target.write_bytes(b"damaged" if action == "broken" else encode_clock(replace(state, high_watermark=datetime.now(UTC).replace(microsecond=0) + timedelta(days=400)), **context))
        print("{}")
elif action == "permissions":
    # Non-root negative probes run with exactly the same mounts as the business service.
    own, other = ("metor", "ai") if os.getuid() == 21001 else ("ai", "metor")
    (root / "identity/service.key").read_bytes()
    (root / "shared/active.license.json").read_bytes()
    try:
        (root / "state" / other / "clock.json").read_bytes()
    except PermissionError:
        pass
    else:
        raise AssertionError("cross-service state readable")
    if own == "ai":
        try:
            (root / "shared/active.license.json").open("ab")
        except OSError:
            pass
        else:
            raise AssertionError("AI commercial mount is writable")
    print(json.dumps({"uid": os.getuid(), "groups": os.getgroups(), "state_isolation": True}))
else:
    raise ValueError("unknown fixture operation")
