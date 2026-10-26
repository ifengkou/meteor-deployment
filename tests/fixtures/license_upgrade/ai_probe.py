"""Isolated verification only: exercise the image's real product license assembly."""

import asyncio
import json
import sys
from importlib.metadata import version
from pathlib import Path

from app.licensing import create_license_resource


async def run():
    command, machine = sys.argv[1:3]
    resource = create_license_resource(Path("/license"), Path(machine))
    runtime = resource.runtime
    if not resource.policy.valid or runtime is None:
        raise AssertionError("product assembly/policy failed")
    try:
        if command == "request":
            result = runtime.commercial_request()
        elif command == "recovery-request":
            result = runtime.get_or_create_recovery_request().to_dict()
        elif command == "recover":
            raw = Path(sys.argv[3]).read_bytes()
            first = runtime.apply_recovery(raw)
            refreshed = runtime.status(read_only=True).state.value
            repeated = runtime.apply_recovery(raw)
            result = {"actionStatus": first.action_status, "repeatStatus": repeated.action_status,
                      "state": first.status.state.value, "refreshedState": refreshed}
        elif command == "worker":
            await resource.start()
            await asyncio.sleep(31)
            result = {"state": runtime.status(read_only=True).state.value}
        else:
            status = runtime.status(read_only=True)
            allowed = True
            try:
                resource.require_valid()
            except Exception:
                allowed = False
            result = {"state": status.state.value, "allowed": allowed}
        result["sdk_version"] = version("metor-license-core")
        print(json.dumps(result, default=str))
    finally:
        # Old product close checkpoints; do not invoke it for read-only inspection.
        if command == "worker" or version("metor-license-core") != "0.6.0":
            await resource.close()


asyncio.run(run())
