"""Exercise the preparation entrypoint without network, Docker, or global pip cache."""

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


class PrepareWheelhouseTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.scripts = self.root / "deployment/scripts"
        self.scripts.mkdir(parents=True)
        for name in ("prepare-wheelhouse.sh", "prepare-wheelhouse.py"):
            shutil.copy2(SCRIPTS / name, self.scripts / name)
        ai = self.root / "ai-runtime-service"
        (ai / "wheelhouse").mkdir(parents=True)
        (ai / "pyproject.toml").write_text("[project]\n")
        self.wheel = ai / "wheelhouse/metor_license_core-0.4.0-py3-none-any.whl"
        self.wheel.write_bytes(b"synthetic-sdk-wheel")
        self.bin = self.root / "bin"
        self.bin.mkdir()
        uv = self.bin / "uv"
        requirements = './wheelhouse/metor_license_core-0.4.0-py3-none-any.whl \\\n    --hash=sha256:0123456789abcdef\ncryptography==46.0.3 \\\n    --hash=sha256:0123456789abcdef\n'
        uv.write_text(
            "#!/usr/bin/env python3\nimport pathlib, sys\n"
            'output = pathlib.Path(sys.argv[sys.argv.index("--output-file") + 1])\n'
            f"output.write_text({requirements!r})\n"
        )
        uv.chmod(0o755)
        docker = self.bin / "docker"
        docker.write_text('''#!/usr/bin/env python3
import json, os, pathlib, sys
pathlib.Path(os.environ["DOCKER_CALL"]).write_text(json.dumps(sys.argv[1:]))
sys.exit(int(os.environ.get("FAKE_DOCKER_RESULT", "0")))
''')
        docker.chmod(0o755)
        self.environment = {**os.environ, "PATH": f"{self.bin}:{os.environ['PATH']}",
                            "TARGET_PLATFORM": "linux/amd64",
                            "DOCKER_CALL": str(self.root / "docker-call.json")}

    def invoke(self, target, **extra):
        return subprocess.run(["sh", str(self.scripts / "prepare-wheelhouse.sh"), str(target)],
                              env={**self.environment, **extra}, capture_output=True, text=True)

    def test_custom_output_stages_local_sdk_and_uses_target_linux_with_closed_validation(self):
        target = self.root / "custom output"
        result = self.invoke(target)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((target / self.wheel.name).read_bytes(), self.wheel.read_bytes())
        arguments = json.loads((self.root / "docker-call.json").read_text())
        self.assertEqual(arguments[arguments.index("--platform") + 1], "linux/amd64")
        self.assertEqual(arguments[arguments.index("--workdir") + 1], "/app")
        self.assertIn(f"type=bind,src={target},dst=/app/wheelhouse", arguments)
        body = arguments[-1]
        self.assertIn("--require-hashes", body)
        self.assertIn("--no-index --no-cache-dir", body)
        self.assertIn("--ignore-installed --dry-run", body)
        self.assertIn("/app/wheelhouse/requirements-linux.txt", body)
        self.assertIn("sys.version_info[:2] == (3, 12)", body)
        self.assertIn(hashlib.sha256(self.wheel.read_bytes()).hexdigest(),
                      (target / "SHA256SUMS").read_text())

    def test_default_wheelhouse_does_not_copy_file_over_itself(self):
        result = self.invoke(self.wheel.parent, TARGET_PLATFORM="linux/arm64")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_missing_sdk_wrong_platform_and_incomplete_dependency_download_fail(self):
        for extra in ({"TARGET_PLATFORM": "darwin/arm64"}, {"TARGET_PYTHON_VERSION": "3.11"},
                      {"FAKE_DOCKER_RESULT": "1"}):
            target = self.root / ("failure-" + next(iter(extra)))
            result = self.invoke(target, **extra)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((target / "SHA256SUMS").exists())
        self.wheel.unlink()
        result = self.invoke(self.root / "missing")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("locked local wheel is missing", result.stderr)


if __name__ == "__main__":
    unittest.main()
