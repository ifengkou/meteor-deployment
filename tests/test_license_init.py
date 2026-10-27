"""Thin maintenance adapter tests; the host never installs/imports the real SDK."""

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import license_container
import license_files
import license_init

IMAGE = "sha256:" + "a" * 64


class InitializationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.root = self.base / "license"
        self.root.mkdir()

    def test_sdk_generates_installation_and_adapter_only_applies_permissions(self):
        sdk = SimpleNamespace(initialize_installation=lambda config, root: SimpleNamespace(
            installation_id="sdk-generated-id", action_status="INITIALIZED"))
        with patch.object(license_init, "load_product", return_value=(object(), "digest")), \
             patch.dict(sys.modules, {"license_sdk.installation": sdk}), \
             patch.object(license_files, "apply_permissions") as permissions:
            self.assertEqual(license_init.run_operation("init", self.root),
                             {"installation_id": "sdk-generated-id", "state": "INITIALIZED"})
            permissions.assert_called_once_with(self.root)

    def test_permission_failure_keeps_sdk_result_for_same_command_retry(self):
        sdk = SimpleNamespace(initialize_installation=lambda *args: SimpleNamespace(
            installation_id="id", action_status="ALREADY_INITIALIZED"))
        with patch.object(license_init, "load_product", return_value=(object(), "digest")), \
             patch.dict(sys.modules, {"license_sdk.installation": sdk}), \
             patch.object(license_files, "apply_permissions", side_effect=PermissionError):
            with self.assertRaisesRegex(ValueError, "OUTCOME_UNKNOWN"):
                license_init.run_operation("init", self.root)

    def test_check_only_calls_readonly_sdk_validator(self):
        sdk = SimpleNamespace(validate_installation=lambda config, root: "installation-id")
        with patch.object(license_init, "load_product", return_value=(object(), "digest")), \
             patch.dict(sys.modules, {"license_sdk.installation": sdk}), \
             patch.object(license_files, "validate_layout") as validate:
            self.assertEqual(license_init.run_operation("check", self.root),
                             {"installation_id": "installation-id", "state": "VALID"})
            validate.assert_called_once_with(self.root)

    def test_unknown_hidden_old_stage_symlink_hardlink_and_special_files_rejected(self):
        for name in (".unknown", ".identity-stage-old", "arbitrary.lock"):
            path = self.root / name
            path.write_bytes(b"preserve")
            with self.assertRaises(ValueError):
                license_files.reviewed_paths(self.root, draft=True)
            self.assertEqual(path.read_bytes(), b"preserve")
            path.unlink()
        target = self.base / "target"
        target.write_text("safe")
        path = self.root / ".init.lock"
        path.symlink_to(target)
        with self.assertRaises(ValueError):
            license_files.reviewed_paths(self.root)
        path.unlink()
        os.link(target, path)
        with self.assertRaises(ValueError):
            license_files.reviewed_paths(self.root)
        path.unlink()
        os.mkfifo(path)
        with self.assertRaises(ValueError):
            license_files.reviewed_paths(self.root)

    def test_host_numeric_identity_preflight(self):
        with patch.object(license_files.os, "geteuid", return_value=501):
            with self.assertRaisesRegex(ValueError, "requires root"):
                license_files.preflight_ids()
        with patch.object(license_files.os, "geteuid", return_value=0), \
             patch.object(license_files.pwd, "getpwuid", return_value=SimpleNamespace(pw_name="other")):
            with self.assertRaisesRegex(ValueError, "another host account"):
                license_files.preflight_ids()

    def test_fixed_image_never_follows_business_image_or_mutable_tags(self):
        for config in ({"AI_RUNTIME_IMAGE": IMAGE}, {"LICENSE_TOOLS_IMAGE": "ai:latest"}):
            with self.assertRaisesRegex(ValueError, "LICENSE_TOOLS_IMAGE"):
                license_container.fixed_image(config, self.base)
        manifest = self.base / "manifest.json"
        manifest.write_text(json.dumps({"licenseToolsImage": IMAGE, "images": [{"id": IMAGE}]}))
        record = SimpleNamespace(stdout=json.dumps([{"Id": IMAGE, "Os": "linux"}]))
        with patch.object(license_container.subprocess, "run", return_value=record):
            self.assertEqual(license_container.fixed_image(
                {"AI_RUNTIME_IMAGE": "rollback:old"}, self.base / "deployment"), IMAGE)

    def test_actual_command_is_offline_and_check_mount_readonly(self):
        tools = object.__new__(license_container.LicenseTools)
        tools.deployment, tools.image = self.base, IMAGE
        (self.base / "scripts").mkdir()
        with patch.object(license_container.subprocess, "run", return_value=SimpleNamespace(stdout="{}")) as run:
            tools.operation("check", self.root)
        command = run.call_args.args[0]
        for flag in ("--pull=never", "--network=none", "--read-only"):
            self.assertIn(flag, command)
        self.assertIn("type=bind,src=" + str(self.root) + ",dst=/run/icp-license,readonly", command)
        self.assertNotIn("/etc/machine-id", " ".join(command))
        self.assertNotIn("app.main", " ".join(command))
        self.assertEqual(command[-3:], ["check", "--root", "/run/icp-license"])

    def test_fixed_tools_resolve_classic_config_digest_without_accepting_another_image(self):
        configuration = "sha256:" + "b" * 64
        entry = {"id": IMAGE, "configId": configuration, "reference": "reviewed:release",
                 "os": "linux", "architecture": "amd64"}
        (self.base / "manifest.json").write_text(json.dumps({"licenseToolsImage": IMAGE, "images": [entry]}))
        actual = {"Id": configuration, "Os": "linux", "Architecture": "amd64"}
        with patch.object(license_container.subprocess, "run", return_value=SimpleNamespace(stdout=json.dumps([actual]))) as run:
            self.assertEqual(license_container.fixed_image(
                {"AI_RUNTIME_IMAGE": "rollback:old"}, self.base / "deployment"), configuration)
            self.assertEqual(run.call_args.args[0][-1], "reviewed:release")
        for change in ({"Id": "sha256:" + "c" * 64}, {"Architecture": "arm64"}):
            with patch.object(license_container.subprocess, "run", return_value=SimpleNamespace(stdout=json.dumps([{**actual, **change}]))):
                with self.assertRaisesRegex(ValueError, "differs"):
                    license_container.fixed_image({}, self.base / "deployment")

    def test_probe_failure_precedes_target_creation(self):
        with patch.object(license_container, "fixed_image", return_value=IMAGE), \
             patch.object(license_container.LicenseTools, "operation", side_effect=ValueError("bad config")):
            with self.assertRaises(ValueError):
                license_container.LicenseTools({}, self.base)
        self.assertEqual(list(self.root.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
