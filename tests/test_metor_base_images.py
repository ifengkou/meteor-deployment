"""Base-image caching must survive architecture and upstream tag changes."""

import subprocess
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import metor_base_images as bases


class MetorBaseImagesTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict("os.environ", {}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_warm_platform_never_pulls_or_tags(self):
        for platform in ("linux/arm64", "linux/amd64"):
            with self.subTest(platform=platform), \
                 patch.object(bases, "inspect_image", return_value="sha256:cached"), \
                 patch.object(bases.subprocess, "run") as run:
                prepared = bases.prepare(platform)
                self.assertTrue(all(ref.endswith(platform.split("/")[1]) for ref in prepared.values()))
                run.assert_not_called()

    def test_switch_preserves_arm64_and_falls_back_to_official_registry(self):
        images = {"eclipse-temurin:21-jdk-jammy": ("sha256:arm", "linux/arm64")}
        commands = []

        def inspect(reference, platform):
            record = images.get(reference)
            return record[0] if record and record[1] == platform else None

        def docker(command, **kwargs):
            commands.append(command)
            if command[1:3] == ["image", "tag"]:
                source, target = command[-2:]
                record = next(record for record in images.values() if record[0] == source)
                images[target] = record
                return SimpleNamespace(returncode=0)
            reference = command[-1]
            if reference.startswith("registry-1.docker.io/"):
                images[reference] = ("sha256:amd-" + reference.split(":")[-1], "linux/amd64")
                return SimpleNamespace(returncode=0)
            return SimpleNamespace(returncode=1)

        with patch.object(bases, "inspect_image", side_effect=inspect), \
             patch.object(bases.subprocess, "run", side_effect=docker):
            prepared = bases.prepare("linux/amd64")
            self.assertEqual(inspect("icp-diag-base/eclipse-temurin:21-jdk-jammy-arm64", "linux/arm64"),
                             "sha256:arm")
            self.assertTrue(all(inspect(ref, "linux/amd64") for ref in prepared.values()))
            count = len(commands)
            bases.prepare("linux/amd64")
            self.assertEqual(len(commands), count)

    def test_index_without_platform_content_is_not_a_cache_hit(self):
        result = SimpleNamespace(returncode=0, stdout="sha256:manifest /\n")
        with patch.object(bases.subprocess, "run", return_value=result):
            self.assertIsNone(bases.inspect_image("base:index", "linux/amd64"))

    def test_older_docker_can_use_a_single_platform_tag(self):
        results = [SimpleNamespace(returncode=1, stdout=""),
                   SimpleNamespace(returncode=0, stdout="sha256:arm linux/arm64\n")]
        with patch.object(bases.subprocess, "run", side_effect=results):
            self.assertEqual(bases.inspect_image("base:arm64", "linux/arm64"), "sha256:arm")

    def test_build_reference_pins_cached_manifest_instead_of_config_id(self):
        result = SimpleNamespace(stdout='["upstream/java@sha256:other", "local/java@sha256:manifest"]')
        with patch.object(bases.subprocess, "run", return_value=result):
            self.assertEqual(bases.pinned_reference("local/java:amd64"),
                             "local/java:amd64@sha256:manifest")

    def test_classic_locally_built_image_can_have_no_repository_digest(self):
        with patch.object(bases.subprocess, "run", return_value=SimpleNamespace(stdout="null")):
            self.assertEqual(bases.pinned_reference("local/java:amd64"), "local/java:amd64")

    def test_custom_source_has_a_separate_cache_and_no_implicit_fallback(self):
        key = "METOR_JDK_IMAGE"
        custom = "registry.example.com/java:21"
        self.assertNotEqual(bases.cache_reference(key, custom, "amd64"),
                            bases.cache_reference(key, bases.DEFAULTS[key], "amd64"))
        with patch.dict("os.environ", {key: custom}), \
             patch.object(bases, "inspect_image", return_value=None), \
             patch.object(bases.subprocess, "run", return_value=SimpleNamespace(returncode=1)) as run:
            with self.assertRaisesRegex(ValueError, key):
                bases.prepare("linux/amd64")
            self.assertEqual(run.call_args.args[0], ["docker", "pull", "--platform", "linux/amd64", custom])
            self.assertEqual(run.call_count, 1)

    def test_refresh_failure_does_not_retag_cached_base(self):
        with patch.object(bases, "inspect_image", return_value="sha256:old"), \
             patch.object(bases.subprocess, "run", return_value=SimpleNamespace(returncode=1)) as run:
            with self.assertRaises(ValueError):
                bases.prepare("linux/amd64", refresh=True)
            self.assertTrue(all(call.args[0][1] == "pull" for call in run.call_args_list))

    def test_tag_failure_stops_preparation(self):
        def inspect(reference, platform):
            return "sha256:source" if reference.startswith("eclipse-temurin:") else None

        with patch.object(bases, "inspect_image", side_effect=inspect), \
             patch.object(bases.subprocess, "run", side_effect=subprocess.CalledProcessError(1, ["tag"])):
            with self.assertRaises(subprocess.CalledProcessError):
                bases.prepare("linux/amd64")


if __name__ == "__main__":
    unittest.main()
