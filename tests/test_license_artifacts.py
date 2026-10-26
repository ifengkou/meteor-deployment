"""Reject altered release binaries and mixed/development customer resources."""

import hashlib
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import license_artifacts as artifacts


class LicenseArtifactTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.raw = json.dumps({"product_id": "icp-diag", "services": [{"id": "metor"}, {"id": "ai"}],
                               "trusted_keys": {"vendor-2026": "public-key"}}).encode()
        (self.root / "images").mkdir()
        (self.root / "images/full-stack.tar").write_bytes(b"archive fixture")
        self.archive_checksum = artifacts.sha256(b"archive fixture") + "  images/full-stack.tar\n"
        (self.root / "SHA256SUMS").write_text(self.archive_checksum)
        self.routes = b'[{"path":"/protected","methods":["POST"]}]'
        self.metadata = {"schema_version": 2, "mode": "CUSTOMER_REQUIRED",
                         "api_routes_sha256": artifacts.sha256(self.routes),
                         "product_config_sha256": artifacts.sha256(self.raw)}

    def test_metadata_must_match_actual_customer_resources(self):
        artifacts.validate_resources(self.metadata, self.raw, self.routes)
        for change in ({"mode": "DEVELOPMENT"}, {"schema_version": True},
                       {"product_config_sha256": "0" * 64}, {"api_routes_sha256": "0" * 64}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                artifacts.validate_resources({**self.metadata, **change}, self.raw, self.routes)
        with self.assertRaises(ValueError):
            artifacts.validate_resources(self.metadata, self.raw + b" ", self.routes)

    def test_test_trust_is_not_a_customer_release(self):
        for key in ("phase1-test-only", "synthetic", "demo-key"):
            data = json.loads(self.raw)
            data["trusted_keys"] = {key: "key"}
            raw = json.dumps(data).encode()
            with self.subTest(key=key), self.assertRaises(ValueError):
                artifacts.validate_resources({**self.metadata, "product_config_sha256": artifacts.sha256(raw)}, raw, self.routes)

    def test_boot_jar_rejects_wrong_or_additional_sdk(self):
        jar = self.root / "app.jar"
        core = b"isolated fake SDK binary"
        digest = hashlib.sha256(core).hexdigest()
        for name, payload in (("valid", core), ("changed", core + b"tampered"), ("old", core)):
            with zipfile.ZipFile(jar, "w") as archive:
                archive.writestr("META-INF/license-product.json", self.raw)
                archive.writestr("META-INF/metor-license-release.json", json.dumps(self.metadata))
                archive.writestr("META-INF/metor-license-routes.json", self.routes)
                archive.writestr("BOOT-INF/lib/license-core-0.7.1.jar", payload)
                if name == "old":
                    archive.writestr("BOOT-INF/lib/license-core-0.6.0.jar", core)
            with patch.dict(artifacts.RELEASE_SHA256, {"license-core-0.7.1.jar": digest}):
                if name == "valid":
                    self.assertEqual(artifacts.inspect_boot_jar(jar), self.raw)
                else:
                    with self.assertRaises(ValueError):
                        artifacts.inspect_boot_jar(jar)

    def test_bundle_manifest_pins_release_tools_and_one_platform(self):
        import copy

        records = [{"id": "sha256:" + str(i) * 64, "reference": f"local:{i}",
                    "os": "linux", "architecture": "arm64"} for i in range(4)]
        valid = {"formatVersion": 1, "images": records, "licenseToolsImage": records[1]["id"],
                 "licensing": {"sdkVersion": artifacts.SDK_VERSION, "mode": "CUSTOMER_REQUIRED",
                               "releaseArtifactsSha256": dict(artifacts.RELEASE_SHA256),
                               "productConfigSha256": "a" * 64}}
        path = self.root / "manifest.json"
        path.write_text(json.dumps(valid))
        self.assertEqual(artifacts.verify_bundle(self.root), valid)
        cases = []
        bad = copy.deepcopy(valid); bad["licensing"]["sdkVersion"] = "0.6.0"; cases.append(bad)
        bad = copy.deepcopy(valid); bad["licensing"]["releaseArtifactsSha256"]["license-core-0.7.1.jar"] = "0" * 64; cases.append(bad)
        bad = copy.deepcopy(valid); bad["licenseToolsImage"] = records[2]["id"]; cases.append(bad)
        bad = copy.deepcopy(valid); bad["images"][2]["architecture"] = "amd64"; cases.append(bad)
        bad = copy.deepcopy(valid); bad["images"][2]["os"] = "darwin"; cases.append(bad)
        bad = copy.deepcopy(valid); bad["images"][2]["id"] = "mutable:latest"; cases.append(bad)
        cases.extend([[], {**valid, "images": [None] * 4}, {**valid, "licensing": []}])
        for candidate in cases:
            with self.subTest(candidate=candidate):
                path.write_text(json.dumps(candidate))
                with self.assertRaises(ValueError):
                    artifacts.verify_bundle(self.root)

    def test_bundle_refuses_uncovered_extra_or_linked_image_archives(self):
        # Files are rejected before manifest parsing or any docker load.
        for content in ("", "0" * 64 + "  another-file\n", self.archive_checksum * 2):
            (self.root / "SHA256SUMS").write_text(content)
            with self.assertRaisesRegex(ValueError, "exactly once"):
                artifacts.verify_bundle(self.root)
        (self.root / "SHA256SUMS").write_text(self.archive_checksum)
        for name in ("old-extra.tar", "unexpected.json"):
            extra = self.root / "images" / name
            extra.write_bytes(b"must not be loaded")
            with self.assertRaisesRegex(ValueError, "only the regular"):
                artifacts.verify_bundle(self.root)
            extra.unlink()
        archive = self.root / "images/full-stack.tar"
        saved = self.root / "saved.tar"
        archive.rename(saved)
        archive.symlink_to(saved)
        with self.assertRaisesRegex(ValueError, "only the regular"):
            artifacts.verify_bundle(self.root)

    def test_build_rejects_changed_public_config_and_binary_before_docker(self):
        roots = [self.root / name for name in ("ai-runtime-service", "metor-service")]
        for root in roots:
            (root / "license-build").mkdir(parents=True)
            (root / "license-build/license-product.json").write_bytes(self.raw)
        with patch.object(artifacts, "verify_input") as verify:
            self.assertEqual(artifacts.verify_build_inputs(self.root), artifacts.sha256(self.raw))
            self.assertEqual(verify.call_count, 2)
            (roots[1] / "license-build/license-product.json").write_bytes(self.raw + b" ")
            with self.assertRaisesRegex(ValueError, "raw bytes differ"):
                artifacts.verify_build_inputs(self.root)
        candidate = self.root / "changed.whl"
        candidate.write_bytes(b"tampered")
        with self.assertRaisesRegex(ValueError, "checksum mismatch"):
            artifacts.verify_input(candidate, "metor_license_core-0.7.1-py3-none-any.whl")
        for relative in ("../secret.json", "/etc/secret.json", "app/license-product.json"):
            with self.subTest(relative=relative), self.assertRaises(ValueError):
                artifacts.verify_build_inputs(self.root, relative)


if __name__ == "__main__":
    unittest.main()
