"""Linux root smoke: real numeric permissions, repeat preparation and path refusal.

Run in a disposable root container with deployment mounted read-only at /deployment.
Image inspection is stubbed; no business service, host runtime or real credentials used.
"""

import importlib.util
import json
import os
import platform
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import customer_bundle as bundle


def main():
    if sys.platform != "linux" or os.geteuid() != 0:
        raise SystemExit("requires disposable Linux root environment")
    spec = importlib.util.spec_from_file_location(
        "prepare_runtime", Path(__file__).resolve().parents[1] / "scripts/prepare-runtime.py")
    prepare = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(prepare)
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        (root / bundle.CREDENTIAL_PATH).parent.mkdir(parents=True)
        private = {key: "synthetic-only-with-enough-length-$-quote'" for key in bundle.CREDENTIAL_KEYS}
        bundle.write_env(root / bundle.CREDENTIAL_PATH, private)
        model = root / bundle.MODEL_PATH
        model.mkdir(parents=True)
        for name in ("config.json", "modules.json", "tokenizer_config.json", "tokenizer.json"):
            (model / name).write_text("{}")
        (model / "model.safetensors").write_bytes(b"synthetic weights")
        (model / "model-manifest.json").write_text(json.dumps({
            "artifactName": "bge-small-zh-v1.5", "dimension": 512,
            "modelSafetensorsSha256": bundle.digest(model / "model.safetensors"),
        }))
        manifest = {
            "formatVersion": 2, "includesCredentials": True, "includesModelWeights": True,
            "images": [{"reference": f"fixture:{i}", "id": f"sha256:{i:064x}",
                        "architecture": "arm64" if platform.machine() in ("aarch64", "arm64")
                        else "amd64"} for i in range(4)],
            "embeddingModel": {"id": "bge-small-zh-v1.5", "path": bundle.MODEL_PATH,
                               "offlineLoadVerified": True, "dimension": 512,
                               "manifestSha256": bundle.digest(model / "model-manifest.json")},
        }
        (root / "SHA256SUMS").write_text("".join(
            f"{bundle.digest(p)}  {p.relative_to(root)}\n"
            for p in root.rglob("*") if p.is_file()
        ))

        def run(command, **kwargs):
            if command[:3] == ["docker", "image", "inspect"]:
                image = next(entry for entry in manifest["images"] if command[-1] in (entry["id"], entry["reference"]))
                return SimpleNamespace(stdout=json.dumps([{"Id": image["id"], "Os": "linux", "Architecture": image["architecture"]}]))
            if command[:2] == ["docker", "run"]:
                uid = "21002" if manifest["images"][1]["id"] in command else "21001"
                return SimpleNamespace(stdout=f"{uid}\n{uid}\n")
            return SimpleNamespace(returncode=0)

        with patch.object(prepare.subprocess, "run", side_effect=run), \
             patch.object(prepare.license_artifacts, "verify_bundle", return_value=manifest):
            prepare.prepare(root)
            env = root / "runtime/config/docker.env"
            before = env.read_bytes()
            prepare.prepare(root)
            assert env.read_bytes() == before
            assert {key: bundle.read_env(env)[key] for key in private} == private
            for name, uid in (("metor", 21001), ("ai/documents", 21002), ("ai/chroma", 21002)):
                info = (root / "runtime/data" / name).stat()
                assert (info.st_uid, info.st_gid, info.st_mode & 0o777) == (uid, uid, 0o750)
            assert env.stat().st_mode & 0o777 == 0o600
            assert (model / "model.safetensors").stat().st_mode & 0o777 == 0o444
            assert not (root / "runtime/license").exists()
            (root / "outside").mkdir()
            (root / "runtime/work/metor").rmdir()
            (root / "runtime/work/metor").symlink_to(root / "outside")
            try:
                prepare.prepare(root)
            except ValueError as error:
                assert "symbolic links" in str(error)
            else:
                raise AssertionError("symlink accepted")
    print("PASS: real Linux ownership, exact credential reuse, idempotence, read-only models, symlink refusal")


if __name__ == "__main__":
    main()
