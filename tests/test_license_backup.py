"""License backup invariants, using isolated synthetic installations only."""

import argparse
import importlib.util
import io
import json
import os
import sys
import tarfile
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import license_backup as licensing
import license_init as installer

spec = importlib.util.spec_from_file_location("backup_stack_test", SCRIPTS / "local-stack.py")
stack = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stack)


class LicenseBackupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.root = self.base / "license"
        installer.initialize_license(
            self.root, now=datetime(2026, 1, 1, tzinfo=timezone.utc),
            ownership=lambda *args: None, key_factory=lambda: b"x" * 32,
        )
        (self.root / "shared/active.license.json").write_bytes(b'{"synthetic":true}')
        os.chmod(self.root / "shared/active.license.json", 0o640)
        self.archive = self.base / licensing.ARCHIVE
        self.host = self.base / "machine-id"
        self.host.write_text("synthetic-machine-id\n")
        self.config = {"LICENSE_ROOT": str(self.root), "LICENSE_MACHINE_ID_PATH": str(self.host)}
        # Production still checks numeric ownership; tests cannot chown on macOS.
        self.addCleanup(patch.stopall)
        self.check_metadata = licensing.check_metadata
        patch.object(licensing, "check_metadata").start()
        patch.object(installer, "preflight_ids").start()

    def create_archive(self):
        fingerprint = licensing.host_fingerprint(self.config, self.base)
        return licensing.backup(self.root, self.archive, fingerprint)

    def test_numeric_owner_modes_and_unreadable_host_identity(self):
        info = SimpleNamespace(st_uid=21001, st_gid=21001, st_mode=0o100600)
        self.check_metadata(info, (21001, 21001, 0o600))
        with self.assertRaises(ValueError):
            self.check_metadata(info, (0, 21000, 0o640))
        with patch.object(installer, "read_regular", side_effect=PermissionError("denied")):
            self.assertIsNone(licensing.host_fingerprint(self.config, self.base))

    def test_compose_relative_paths_ignore_invocation_directory(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(licensing.license_root({}, self.base / "deployment"),
                             self.base / "deployment/../runtime/license")
            self.assertEqual(licensing.license_root({"LICENSE_ROOT": "custom"}, self.base),
                             self.base / "custom")
            with patch.dict(os.environ, {"LICENSE_ROOT": str(self.root)}):
                self.assertEqual(licensing.license_root({"LICENSE_ROOT": "wrong"}, self.base),
                                 self.root)

    def test_backup_preserves_state_and_reviewed_metadata_excludes_locks(self):
        (self.root / "state/metor/clock.lock").write_text("not-state")
        (self.root / "shared/.upload-tmp").write_text("incomplete")
        metadata = self.create_archive()
        contents = licensing.validate_archive(self.archive, metadata)
        self.assertEqual(contents["identity/service.key"], b"x" * 32)
        for name, content in contents.items():
            self.assertEqual(content, (self.root / name).read_bytes())
        self.assertEqual(self.archive.stat().st_mode & 0o777, 0o600)
        with tarfile.open(self.archive) as source:
            self.assertFalse(any(member.name.endswith(".lock") or "tmp" in member.name for member in source))

    def test_symlinks_are_refused_even_when_named_temporary(self):
        (self.root / "shared/.tmp").symlink_to(self.host)
        with self.assertRaisesRegex(ValueError, "symbolic"):
            self.create_archive()

    def test_archive_rejects_traversal_links_duplicate_and_unreviewed_permissions(self):
        metadata = self.create_archive()
        with self.assertRaises(ValueError):
            licensing.validate_archive(self.archive, [])
        for name, entry_type, mode in (("../escape", tarfile.REGTYPE, 0o600),
                                       ("identity/service.key", tarfile.SYMTYPE, 0o640),
                                       ("identity/service.key", tarfile.REGTYPE, 0o777)):
            bad = self.base / "bad.tar.gz"
            with tarfile.open(bad, "w:gz") as output:
                member = tarfile.TarInfo(name)
                member.type, member.mode = entry_type, mode
                member.uid, member.gid = 0, 21000
                output.addfile(member)
            with self.assertRaises(ValueError):
                licensing.validate_archive(bad, metadata)
        with tarfile.open(self.archive, "r:gz") as source:
            entries = [(m, source.extractfile(m).read() if m.isfile() else None) for m in source]
        with tarfile.open(bad, "w:gz") as output:
            for member, content in entries + [entries[0]]:
                output.addfile(member, io.BytesIO(content) if content else None)
        with self.assertRaises(ValueError):
            licensing.validate_archive(bad, metadata)

    def test_same_host_empty_restore_preserves_identity_key_clock(self):
        metadata = self.create_archive()
        target = self.base / "empty-target"
        target.mkdir()
        with patch.object(os, "chown"), patch.object(os, "fchown"):
            stage = licensing.prepare_restore(
                target, self.archive, metadata, metadata["machineIdSha256"]
            )
            licensing.publish_restore(target, stage)
        for path in target.rglob("*"):
            if path.is_file():
                self.assertEqual(path.read_bytes(), (self.root / path.relative_to(target)).read_bytes())
        self.assertFalse(list(self.base.glob(".license-restore-*")))

    def test_missing_host_nonempty_and_other_host_refused(self):
        metadata = self.create_archive()
        for fingerprint, target in ((None, self.base / "new"), ("different-host", self.base / "new"),
                                    (metadata["machineIdSha256"], self.root)):
            with self.assertRaises(ValueError):
                licensing.prepare_restore(target, self.archive, metadata, fingerprint)
        self.assertFalse(list(self.base.glob(".license-restore-*")))

    def test_legacy_backup_preserves_valid_identity_never_initializes(self):
        before = (self.root / "identity/installation.json").read_bytes()
        with patch.object(installer, "initialize_license") as initialize:
            self.assertIsNone(licensing.prepare_restore(self.root, None, None, None))
            with self.assertRaises(ValueError):
                licensing.prepare_restore(self.base / "missing", None, None, None)
            initialize.assert_not_called()
        self.assertEqual((self.root / "identity/installation.json").read_bytes(), before)

    def test_bad_clock_rejected_and_staging_failure_cleaned(self):
        metadata = self.create_archive()
        with patch.object(os, "chown", side_effect=PermissionError("denied")):
            with self.assertRaises(PermissionError):
                licensing.prepare_restore(self.base / "new", self.archive, metadata,
                                          metadata["machineIdSha256"])
        self.assertFalse(list(self.base.glob(".license-restore-*")))
        (self.root / "state/ai/clock.json").write_bytes(b"broken")
        with self.assertRaises(ValueError):
            licensing.read_installation(self.root)

    def test_stack_backup_manifest_and_checksums_include_private_license_archive(self):
        env = self.base / "deployment.env"
        model = self.base / "model.json"
        model.write_text("{}")
        env.write_text("\n".join(f"{key}={value}" for key, value in {
            **self.config, "AI_EMBEDDING_MODELS_CONFIG_HOST_PATH": str(model)
        }.items()))
        target = self.base / "backup"
        with patch.object(stack, "compose", return_value=SimpleNamespace(stdout="")):
            stack.backup_stack(argparse.Namespace(env_file=env, backup=target))
        manifest = json.loads((target / "backup-manifest.json").read_text())
        self.assertEqual(manifest["licenseState"]["archive"], licensing.ARCHIVE)
        self.assertIn(licensing.ARCHIVE, (target / "SHA256SUMS").read_text())
        for path in target.iterdir():
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_bad_license_restore_refuses_before_business_sql(self):
        self.test_stack_backup_manifest_and_checksums_include_private_license_archive()
        target = self.base / "backup"
        env = self.base / "deployment.env"
        for name in ("ai-data.tar.gz", "metor-data.tar.gz"):
            with tarfile.open(target / name, "w:gz") as output:
                for directory in (".", "documents", "chroma"):
                    entry = tarfile.TarInfo(directory)
                    entry.type = tarfile.DIRTYPE
                    output.addfile(entry)
        (target / "SHA256SUMS").write_text("".join(
            f"{stack.file_sha256(path)}  {path.name}\n"
            for path in target.iterdir() if path.name != "SHA256SUMS"
        ))
        with patch.object(stack, "mysql") as mysql, patch.object(stack, "compose") as compose:
            with self.assertRaisesRegex(ValueError, "nonempty"):
                stack.restore_stack(argparse.Namespace(env_file=env, backup=target))
            mysql.assert_not_called()
            compose.assert_not_called()


if __name__ == "__main__":
    unittest.main()
