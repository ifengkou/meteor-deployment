"""Installer tests only use temporary roots and synthetic providers; no machine-id or SDK."""

import base64
import hashlib
import importlib.util
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "license_init", Path(__file__).resolve().parents[1] / "scripts/license_init.py"
)
installer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(installer)
NOW = datetime(2026, 10, 21, tzinfo=timezone.utc)
INSTALLATION = "11111111-1111-4111-8111-111111111111"
KEY = bytes(range(32))


class InitializationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve() / "license"
        self.options = {"now": NOW, "ownership": lambda path, uid, gid: None,
                        "id_factory": lambda: INSTALLATION, "key_factory": lambda: KEY}

    def initialize(self, **kwargs):
        return installer.initialize_license(self.root, **{**self.options, **kwargs})

    def test_fresh_and_repeat_preserve_all_bytes(self):
        first = self.initialize()
        self.assertEqual(first, {"installation_id": INSTALLATION, "state": "INITIALIZED"})
        before = {str(p.relative_to(self.root)): p.read_bytes()
                  for p in self.root.rglob("*") if p.is_file()}
        repeated = self.initialize()
        self.assertEqual(repeated["state"], "ALREADY_INITIALIZED")
        after = {str(p.relative_to(self.root)): p.read_bytes()
                 for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(before, after)
        self.assertEqual((self.root / "identity").stat().st_mode & 0o777, 0o750)
        self.assertEqual((self.root / "identity/service.key").stat().st_mode & 0o777, 0o640)
        self.assertEqual((self.root / "state/ai").stat().st_mode & 0o777, 0o700)
        self.assertEqual((self.root / "state/metor/clock.json").stat().st_mode & 0o777, 0o600)

    def test_interrupted_draft_key_and_each_seed_resume_same_identity(self):
        for point in ("draft_written", "key_written", "metor_seed_written", "ai_seed_written"):
            with self.subTest(point=point):
                self.root = Path(self.temporary.name).resolve() / point
                def crash(actual):
                    if point == actual:
                        raise OSError("synthetic interruption")
                with self.assertRaises(OSError):
                    self.initialize(failpoint=crash)
                self.assertEqual((self.root / "identity/service.key").read_bytes(), KEY)
                original = json.loads((self.root / "identity/installation.json").read_bytes())
                self.assertFalse(original["initialized"])
                self.assertEqual(self.initialize()["installation_id"], original["installation_id"])
                self.assertEqual((self.root / "identity/service.key").read_bytes(), KEY)

    def test_completed_missing_clock_not_recreated(self):
        self.initialize()
        path = self.root / "state/metor/clock.json"
        path.unlink()
        with self.assertRaises(OSError):
            self.initialize()
        self.assertFalse(path.exists())

    def test_completed_missing_key_not_recreated(self):
        self.initialize()
        key = self.root / "identity/service.key"
        key.unlink()
        with self.assertRaises(OSError):
            self.initialize()
        self.assertFalse(key.exists())

    def test_corrupted_clock_and_identity_are_not_repaired(self):
        self.initialize()
        clock = self.root / "state/ai/clock.json"
        clock.write_bytes(b"{}")
        with self.assertRaises(ValueError):
            self.initialize()
        self.assertEqual(clock.read_bytes(), b"{}")

    def test_orphan_state_rejected(self):
        (self.root / "state/metor").mkdir(parents=True)
        (self.root / "state/metor/clock.json").write_text("unowned")
        with self.assertRaises(ValueError):
            self.initialize()
        self.assertFalse((self.root / "identity/installation.json").exists())

    def test_symlink_root_rejected(self):
        target = Path(self.temporary.name).resolve() / "target"
        target.mkdir()
        self.root.symlink_to(target, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.initialize()
        self.assertEqual(list(target.iterdir()), [])

    def test_symlink_clock_rejected(self):
        self.initialize()
        clock = self.root / "state/ai/clock.json"
        saved = self.root / "saved"
        clock.rename(saved)
        clock.symlink_to(saved)
        with self.assertRaises((ValueError, OSError)):
            self.initialize()

    def test_complete_wrong_permissions_are_not_silently_fixed(self):
        self.initialize()
        key = self.root / "identity/service.key"
        key.chmod(0o666)
        with self.assertRaises(ValueError):
            self.initialize()
        self.assertEqual(key.stat().st_mode & 0o777, 0o666)

    def test_valid_seed_vector_and_domain_separation(self):
        fixture = json.loads((Path(__file__).resolve().parents[1]
                              / "config/clock-state-v1-vectors.json").read_text())
        for vector in fixture["vectors"]:
            raw = installer.seed_clock(INSTALLATION, KEY, vector["service"], NOW)
            self.assertEqual(raw.decode(), vector["envelope"])
            self.assertEqual(hashlib.sha256(raw).hexdigest(), vector["sha256"])
            decoded = installer.validate_clock(raw, INSTALLATION, KEY, vector["service"])
            self.assertEqual(decoded["high_watermark"], "2026-10-21T00:00:00Z")
            other = "ai" if vector["service"] == "metor" else "metor"
            with self.assertRaises(ValueError):
                installer.validate_clock(raw, INSTALLATION, KEY, other)

    def test_wrong_hmac_unknowns_duplicate_counter_types_and_context(self):
        raw = installer.seed_clock(INSTALLATION, KEY, "ai", NOW)
        outer = json.loads(raw)
        bad = dict(outer, extra=1)
        with self.assertRaises(ValueError):
            installer.validate_clock(installer.canonical(bad), INSTALLATION, KEY, "ai")
        with self.assertRaises(ValueError):
            installer.validate_clock(raw.replace(b'"mac":', b'"mac":"AA","mac":'),
                                     INSTALLATION, KEY, "ai")
        payload = json.loads(base64.urlsafe_b64decode(outer["payload"] + "=="))
        for field, value in (("sequence", True), ("epoch", -1), ("sequence", 2**63),
                             ("product_id", "another"), ("service", "metor")):
            data = dict(payload)
            data[field] = value
            encoded = installer.canonical(data)
            import hmac
            key = hmac.digest(KEY, b"icp-diag/state/ai/v1", "sha256")
            candidate = installer.canonical({"payload": installer._b64(encoded),
                "mac": installer._b64(hmac.digest(key, encoded, "sha256"))})
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                installer.validate_clock(candidate, INSTALLATION, KEY, "ai")

    def test_draft_with_missing_key_refuses_regeneration(self):
        def crash(point):
            if point == "key_written":
                raise OSError("synthetic interruption")
        with self.assertRaises(OSError):
            self.initialize(failpoint=crash)
        key = self.root / "identity/service.key"
        key.unlink()
        with self.assertRaises(OSError):
            self.initialize()
        self.assertFalse(key.exists())

    def test_privileged_ids_preflight_without_changing_host(self):
        with patch.object(installer.os, "geteuid", return_value=501):
            with self.assertRaisesRegex(ValueError, "requires root"):
                installer.preflight_ids()

    def test_directory_sync_failure_does_not_claim_completed(self):
        with patch.object(installer, "_sync_directory", side_effect=OSError("synthetic fsync")):
            with self.assertRaises(OSError):
                self.initialize()
        identity = self.root / "identity/installation.json"
        if identity.exists():
            self.assertFalse(json.loads(identity.read_bytes())["initialized"])


if __name__ == "__main__":
    unittest.main()
