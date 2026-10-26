"""Isolated Linux proof using the installed release SDK, never a sibling source checkout.

Run inside the reviewed AI image as root with /proof on a disposable native Linux volume.
Mount deployment/scripts at /opt/license-tools and add it to PYTHONPATH alongside /app.
"""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import license_backup
import license_files
import license_init
from license_sdk import installation

BASE = Path("/proof")
ROOT = BASE / "license"
RESULTS = []


def snapshot(root):
    return {str(path.relative_to(root)): (hashlib.sha256(path.read_bytes()).hexdigest(),
            path.stat().st_uid, path.stat().st_gid, path.stat().st_mode & 0o777)
            for path in root.rglob("*") if path.is_file() and str(path.relative_to(root)) not in license_files.LOCKS}


def expected_error(action):
    try:
        action()
    except (OSError, ValueError):
        return
    raise AssertionError("operation unexpectedly succeeded")


def check(root):
    return license_init.run_operation("check", root)["installation_id"]


def dropped(service, code):
    uid = {"metor": 21001, "ai": 21002}[service]
    def demote():
        os.setgroups([21000])
        os.setgid(uid)
        os.setuid(uid)
    subprocess.run([sys.executable, "-c", code], check=True, preexec_fn=demote)


def run():
    BASE.chmod(0o755)
    ROOT.mkdir()
    first = license_init.run_operation("init", ROOT)
    assert first["state"] == "INITIALIZED"
    before = snapshot(ROOT)
    assert license_init.run_operation("init", ROOT)["state"] == "ALREADY_INITIALIZED"
    assert before == snapshot(ROOT)
    assert check(ROOT) == first["installation_id"]
    RESULTS.append("sdk-init-repeat-preserves-bytes-owner-mode")

    # SDK creates a valid draft; product code never fabricates its identity or clock.
    draft = BASE / "draft"
    draft.mkdir()
    rename = installation.os.rename
    def interrupted(source, target):
        if Path(source).name == ".identity-stage":
            raise OSError("isolated interruption before identity publication")
        return rename(source, target)
    with patch.object(installation.os, "rename", side_effect=interrupted):
        expected_error(lambda: license_init.run_operation("init", draft))
    staged = {p.name: p.read_bytes() for p in (draft / ".identity-stage").iterdir()}
    license_init.run_operation("init", draft)
    assert (draft / "identity/service.key").read_bytes() == staged["service.key"]
    assert json.loads((draft / "identity/installation.json").read_bytes())["installation_id"] == json.loads(staged["installation.json"])["installation_id"]
    RESULTS.append("sdk-valid-draft-resume")

    retry = BASE / "permissions-retry"
    retry.mkdir()
    with patch.object(license_files, "apply_permissions", side_effect=PermissionError("isolated failure")):
        expected_error(lambda: license_init.run_operation("init", retry))
    prior_bytes = {str(p.relative_to(retry)): p.read_bytes() for p in retry.rglob("*") if p.is_file()}
    assert license_init.run_operation("init", retry)["state"] == "ALREADY_INITIALIZED"
    assert prior_bytes == {str(p.relative_to(retry)): p.read_bytes() for p in retry.rglob("*") if p.is_file()}
    RESULTS.append("permission-retry-preserves-completed-sdk-data")

    # Check accepts missing/invalid/expired commercial bytes and never updates clock.
    commercial = ROOT / "shared/active.license.json"
    for content in (None, b'{"expired":true}', b'not-a-license'):
        if content is not None:
            commercial.write_bytes(content)
            os.chown(commercial, 21001, 21000)
            commercial.chmod(0o640)
        before = snapshot(ROOT)
        check(ROOT)
        assert before == snapshot(ROOT)
    RESULTS.append("sdk-check-readonly-independent-of-commercial-state")

    def permission_code(service):
        other = "ai" if service == "metor" else "metor"
        return "\n".join([
            "from pathlib import Path", "r=Path('/proof/license')",
            "assert len((r/'identity/service.key').read_bytes())==32",
            "assert (r/'shared/active.license.json').read_bytes()",
            f"(r/'state/{service}/" + ("clock.json.lock" if service == "metor" else "clock.lock") + "').write_bytes(b'')",
            f"assert not __import__('os').access(r/'state/{other}/clock.json',__import__('os').W_OK)",
            "assert not __import__('os').access(r/'identity/service.key',__import__('os').W_OK)",
            "assert " + ("" if service == "metor" else "not ") + "__import__('os').access(r/'shared',__import__('os').W_OK)",
        ])
    dropped("metor", permission_code("metor"))
    dropped("ai", permission_code("ai"))
    RESULTS.append("linux-21001-21002-21000-separate-state-and-shared-read")

    before = snapshot(ROOT)
    archive = BASE / license_backup.ARCHIVE
    metadata = license_backup.backup(ROOT, archive, "synthetic-host-sha", check)
    target = BASE / "restored"
    stage = license_backup.prepare_restore(target, archive, metadata, "synthetic-host-sha", check)
    license_backup.publish_restore(target, stage)
    assert before == snapshot(target)
    assert before == snapshot(ROOT)
    expected_error(lambda: license_backup.prepare_restore(ROOT, archive, metadata, "synthetic-host-sha", check))
    expected_error(lambda: license_backup.prepare_restore(BASE / "other-host", archive, metadata, "wrong", check))
    assert license_backup.prepare_restore(ROOT, None, None, None, check) is None
    RESULTS.append("sdk-checked-backup-restore-exact-bytes-metadata-same-host-empty-target")

    clock = ROOT / "state/ai/clock.json"
    valid = clock.read_bytes()
    clock.write_bytes(b"broken")
    before = snapshot(ROOT)
    expected_error(lambda: check(ROOT))
    expected_error(lambda: license_init.run_operation("init", ROOT))
    assert before == snapshot(ROOT)
    clock.unlink()
    expected_error(lambda: license_init.run_operation("init", ROOT))
    assert not clock.exists()
    clock.write_bytes(valid)
    os.chown(clock, 21002, 21002)
    clock.chmod(0o600)
    check(ROOT)
    RESULTS.append("damaged-completed-clock-rejected-without-repair")

    # Pre-write image/config validation failure (only public temp resources involved).
    with patch.object(license_init, "version", return_value="0.6.0"):
        expected_error(lambda: license_init.run_operation("probe"))
    resources = BASE / "invalid-resources"
    resources.mkdir()
    (resources / "_license_build.json").write_text('{"schema_version":1}')
    (resources / "license-product.json").write_text('{}')
    with patch.object(license_init, "files", return_value=resources):
        expected_error(lambda: license_init.run_operation("probe"))
    RESULTS.append("wrong-sdk-or-config-rejected-before-target-write")
    print(json.dumps({"platform": sys.platform, "architecture": os.uname().machine,
                      "sdk_version": license_init.SDK_VERSION, "passed": RESULTS}))


if __name__ == "__main__":
    run()
