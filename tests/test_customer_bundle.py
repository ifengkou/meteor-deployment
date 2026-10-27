"""Complete payload, literal credentials, compressed export and Linux preparation."""

import argparse
import importlib.util
import json
import os
import subprocess
import sys
import tarfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import customer_bundle as bundle


def load_script(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), SCRIPTS / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def model_fixture(root):
    root.mkdir(parents=True)
    for name in ("config.json", "modules.json", "tokenizer_config.json", "tokenizer.json"):
        (root / name).write_text("{}")
    (root / "model.safetensors").write_bytes(b"synthetic model weights")
    (root / "model-manifest.json").write_text(json.dumps({
        "artifactName": "bge-small-zh-v1.5", "dimension": 512,
        "modelSafetensorsSha256": bundle.digest(root / "model.safetensors"),
    }))


def private_fixture(path):
    values = {key: "synthetic $value 'quoted' \\ suffix with enough length"
              for key in bundle.CREDENTIAL_KEYS}
    path.parent.mkdir(parents=True, exist_ok=True)
    bundle.write_env(path, values)
    return values


def complete_fixture(root):
    private_fixture(root / bundle.CREDENTIAL_PATH)
    model_fixture(root / bundle.MODEL_PATH)
    images = [{"reference": f"fixture:{i}", "id": "sha256:" + str(i) * 64,
               "os": "linux", "architecture": "amd64"} for i in range(4)]
    manifest = {"formatVersion": 2, "includesCredentials": True, "includesModelWeights": True,
                "images": images, "embeddingModel": {
                    "id": "bge-small-zh-v1.5", "path": bundle.MODEL_PATH,
                    "manifestSha256": bundle.digest(root / bundle.MODEL_PATH / "model-manifest.json"),
                    "dimension": 512, "offlineLoadVerified": True}}
    (root / "SHA256SUMS").write_text("".join(
        f"{bundle.digest(p)}  {p.relative_to(root)}\n" for p in root.rglob("*") if p.is_file()
    ))
    return manifest


def test_credentials_roundtrip_and_url_encoding(tmp_path):
    private = private_fixture(tmp_path / bundle.CREDENTIAL_PATH)
    manifest = {"images": [{"reference": f"fixture:{i}", "architecture": "amd64"}
                           for i in range(4)]}
    values = bundle.runtime_config(tmp_path, manifest)
    assert {key: values[key] for key in private} == private
    assert "%24" in values["AI_DB_URL"] and "%27" in values["AI_DB_URL"]
    assert "p6-local" not in str(values)
    target = tmp_path / "docker.env"
    bundle.write_env(target, values)
    assert bundle.read_env(target) == values
    assert target.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        bundle.write_env(target, values)


def test_read_env_export_prefix_preserves_keys_and_quoted_values(tmp_path):
    path = tmp_path / "source.env"
    path.write_text("export PASSWORD='value with $ and = signs'\nexported=value\n  export EMPTY=  # comment\n")
    assert bundle.read_env(path) == {"PASSWORD": "value with $ and = signs",
                                     "exported": "value", "EMPTY": ""}


def test_bundled_compose_rejects_wrong_binary_and_tampering(tmp_path):
    source = tmp_path / "download"
    source.write_bytes(b"synthetic executable")
    target = tmp_path / "bundle" / bundle.COMPOSE_PATH
    with pytest.raises(ValueError, match="official"):
        bundle.package_compose(source, target)
    with patch.object(bundle, "COMPOSE_SHA256", bundle.digest(source)):
        record = bundle.package_compose(source, target)
        assert target.stat().st_mode & 0o777 == 0o755
        assert bundle.verify_compose(tmp_path / "bundle", record) == target
        target.chmod(0o644)
        with pytest.raises(ValueError, match="executable"):
            bundle.verify_compose(tmp_path / "bundle", record)
        target.chmod(0o755)
        target.write_bytes(b"changed")
        with pytest.raises(ValueError, match="changed"):
            bundle.verify_compose(tmp_path / "bundle", record)


def test_compose_preserves_synthetic_special_character_credentials(tmp_path):
    import shutil

    if shutil.which("docker") is None:
        pytest.skip("Compose CLI unavailable")
    values = private_fixture(tmp_path / "private.env")
    compose = tmp_path / "compose.yaml"
    compose.write_text("services:\n  test:\n    image: fixture:1\n    environment:\n      VALUE: ${AI_DB_PASSWORD}\n")
    result = subprocess.run([
        "docker", "compose", "--env-file", str(tmp_path / "private.env"),
        "-f", str(compose), "config", "--environment",
    ], check=True, capture_output=True, text=True)
    assert "AI_DB_PASSWORD=" + values["AI_DB_PASSWORD"] in result.stdout.splitlines()


def test_model_requires_real_weights_tokenizer_and_matching_digest(tmp_path):
    root = tmp_path / "model"
    model_fixture(root)
    bundle.validate_model(root)
    (root / "model.safetensors").write_bytes(b"version https://git-lfs.github.com/spec/v1\n")
    with pytest.raises(ValueError, match="LFS"):
        bundle.validate_model(root)
    (root / "model.safetensors").write_bytes(b"changed real weight file")
    with pytest.raises(ValueError, match="reviewed"):
        bundle.validate_model(root)
    (root / "tokenizer.json").unlink()
    with pytest.raises(ValueError, match="tokenizer"):
        bundle.validate_model(root)


def test_packaged_model_is_loaded_in_fixed_image_offline(tmp_path):
    source, target = tmp_path / "source", tmp_path / "packaged"
    model_fixture(source)
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(stdout='{"dimension": 512}')
    result = bundle.package_model(source, target, "sha256:" + "1" * 64, run)
    assert result["offlineLoadVerified"] is True
    assert "--network=none" in calls[0]
    assert "sha256:" + "1" * 64 in calls[0]
    assert bundle.digest(target / "model.safetensors") == bundle.digest(source / "model.safetensors")


def test_payload_verification_catches_removed_and_changed_files(tmp_path):
    manifest = complete_fixture(tmp_path)
    bundle.verify_contents(tmp_path, manifest)
    tokenizer = tmp_path / bundle.MODEL_PATH / "tokenizer.json"
    tokenizer.write_text('{"changed": true}')
    with pytest.raises(ValueError, match="checksum"):
        bundle.verify_contents(tmp_path, manifest)
    tokenizer.write_text("{}")
    sums = tmp_path / "SHA256SUMS"
    sums.write_text("\n".join(x for x in sums.read_text().splitlines() if bundle.CREDENTIAL_PATH not in x))
    with pytest.raises(ValueError, match="cover"):
        bundle.verify_contents(tmp_path, manifest)


def test_format_two_passes_release_verifier_with_complete_payload(tmp_path):
    import license_artifacts

    manifest = complete_fixture(tmp_path)
    (tmp_path / "images").mkdir()
    (tmp_path / "images/full-stack.tar").write_bytes(b"synthetic image archive")
    manifest.update({
        "licenseToolsImage": manifest["images"][1]["id"],
        "licensing": {"sdkVersion": license_artifacts.SDK_VERSION, "mode": "CUSTOMER_REQUIRED",
                      "releaseArtifactsSha256": dict(license_artifacts.RELEASE_SHA256),
                      "productConfigSha256": "a" * 64},
    })
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))
    (tmp_path / "SHA256SUMS").write_text("".join(
        f"{bundle.digest(p)}  {p.relative_to(tmp_path)}\n"
        for p in tmp_path.rglob("*") if p.is_file() and p.name != "SHA256SUMS"
    ))
    assert license_artifacts.verify_bundle(tmp_path) == manifest
    manifest["includesModelWeights"] = False
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="must include"):
        license_artifacts.verify_bundle(tmp_path)


def test_tar_export_roundtrip_and_refuses_overwrite(tmp_path):
    stack = load_script("local-stack")
    output = tmp_path / "customer.tar.gz"
    def export(args):
        args.output.mkdir()
        (args.output / "payload").write_text("fixture")
    with patch.object(stack, "export_directory", side_effect=export):
        stack.export_bundle(argparse.Namespace(output=output))
        with pytest.raises(FileExistsError):
            stack.export_bundle(argparse.Namespace(output=output))
    with tarfile.open(output) as archive:
        assert archive.extractfile("customer/payload").read() == b"fixture"
    assert output.stat().st_mode & 0o777 == 0o600
    assert output.with_name(output.name + ".sha256").read_text().startswith(bundle.digest(output))


def test_prepare_preserves_existing_env_before_any_mutation(tmp_path):
    prepare = load_script("prepare-runtime")
    manifest = complete_fixture(tmp_path)
    target = tmp_path / "runtime/config/docker.env"
    target.parent.mkdir(parents=True)
    target.write_text("EXISTING=preserve\n")
    with patch.object(prepare.sys, "platform", "linux"), \
         patch.object(prepare.platform, "machine", return_value="x86_64"), \
         patch.object(prepare.license_files, "preflight_ids"), \
         patch.object(prepare.subprocess, "run"), \
         patch.object(prepare.license_artifacts, "verify_bundle", return_value=manifest), \
         patch.object(prepare.os, "chown") as chown:
        with pytest.raises(ValueError, match="existing docker.env"):
            prepare.prepare(tmp_path)
        chown.assert_not_called()
    assert target.read_text() == "EXISTING=preserve\n"


@pytest.mark.skipif(sys.platform != "linux" or os.geteuid() != 0,
                    reason="actual numeric ownership requires Linux root")
def test_prepare_actual_linux_ownership_idempotence_and_symlink_refusal(tmp_path):
    prepare = load_script("prepare-runtime")
    manifest = complete_fixture(tmp_path)
    def run(command, **kwargs):
        if command[:3] == ["docker", "image", "inspect"]:
            image = next(entry for entry in manifest["images"] if command[-1] in (entry["id"], entry["reference"]))
            return SimpleNamespace(stdout=json.dumps([{"Id": image["id"], "Os": "linux", "Architecture": "amd64"}]))
        if command[:2] == ["docker", "run"]:
            uid = "21002" if manifest["images"][1]["id"] in command else "21001"
            return SimpleNamespace(stdout=uid + "\n" + uid + "\n")
        return SimpleNamespace(returncode=0)
    with patch.object(prepare.platform, "machine", return_value="x86_64"), \
         patch.object(prepare.subprocess, "run", side_effect=run), \
         patch.object(prepare.license_artifacts, "verify_bundle", return_value=manifest):
        prepare.prepare(tmp_path)
        before = (tmp_path / "runtime/config/docker.env").read_bytes()
        prepare.prepare(tmp_path)
        assert (tmp_path / "runtime/config/docker.env").read_bytes() == before
        assert (tmp_path / "runtime/data/metor").stat().st_uid == 21001
        assert (tmp_path / "runtime/data/ai/documents").stat().st_uid == 21002
        assert (tmp_path / "runtime/config/docker.env").stat().st_mode & 0o777 == 0o600
        assert not (tmp_path / "runtime/license").exists()
        outside = tmp_path / "outside"
        outside.mkdir()
        (tmp_path / "runtime/work/metor").rmdir()
        (tmp_path / "runtime/work/metor").symlink_to(outside)
        with pytest.raises(ValueError, match="symbolic links"):
            prepare.prepare(tmp_path)
