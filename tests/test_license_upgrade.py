"""Protect the fixture driver's binary provenance and platform boundary."""

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

spec = importlib.util.spec_from_file_location(
    "license_upgrade", Path(__file__).resolve().parents[1] / "scripts/verify-license-sdk-upgrade.py")
upgrade = importlib.util.module_from_spec(spec)
spec.loader.exec_module(upgrade)


class UpgradeDriverTest(unittest.TestCase):
    def test_arm_images_cannot_be_reported_as_amd64(self):
        record = [{"Os": "linux", "Architecture": "arm64", "Id": "sha256:" + "a" * 64}]
        with patch.object(upgrade, "execute", return_value=json.dumps(record)):
            with self.assertRaisesRegex(ValueError, "does not match"):
                upgrade.image_info("local:old", "linux/amd64")

    def test_test_trust_patch_preserves_nested_sdk_bytes_and_storage(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, target = root / "source.jar", root / "patched.jar"
            sdk = b"reviewed SDK binary"
            with zipfile.ZipFile(source, "w") as archive:
                archive.writestr("META-INF/metor-license-release.json", json.dumps({
                    "schema_version": 2, "product_config_sha256": "old", "mode": "CUSTOMER_REQUIRED"}))
                archive.writestr("META-INF/license-product.json", b"old")
                entry = zipfile.ZipInfo("BOOT-INF/lib/license-core-0.7.1.jar")
                entry.compress_type = zipfile.ZIP_STORED
                archive.writestr(entry, sdk)
                archive.writestr("BOOT-INF/classes/product.class", b"real product class")
            with patch.object(upgrade, "SDK_JAR_SHA", upgrade.digest(sdk)):
                upgrade.patch_jar(source, target, b"new public fixture", "DER")
            with zipfile.ZipFile(target) as archive:
                self.assertEqual(archive.read(entry.filename), sdk)
                self.assertEqual(archive.getinfo(entry.filename).compress_type, zipfile.ZIP_STORED)
                self.assertEqual(archive.read("BOOT-INF/classes/product.class"), b"real product class")
                self.assertEqual(len(archive.namelist()), len(set(archive.namelist())))

    def test_unreviewed_sdk_is_rejected_before_patch(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with zipfile.ZipFile(root / "source.jar", "w") as archive:
                archive.writestr("META-INF/metor-license-release.json", '{"schema_version":2}')
                archive.writestr("BOOT-INF/lib/license-core-0.7.1.jar", b"tampered")
            with self.assertRaisesRegex(ValueError, "reviewed Release"):
                upgrade.patch_jar(root / "source.jar", root / "patched.jar", b"{}", "DER")


if __name__ == "__main__":
    unittest.main()
