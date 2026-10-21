from __future__ import annotations

import io
import json
import subprocess
import sys
import tarfile
from pathlib import Path

DEPLOYMENT = Path(__file__).resolve().parents[1]
REPO_ROOT = DEPLOYMENT.parent


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")




def test_standalone_compose_has_migration_gate_and_isolation() -> None:
    compose = read(DEPLOYMENT / "compose.ai.yaml")
    assert "mysql:" in compose
    assert "ai-migrate:" in compose
    assert "ai-runtime:" in compose
    assert "condition: service_completed_successfully" in compose
    assert "/internal/health/ready" in compose
    assert "/models/embedding:ro" in compose
    assert "cap_drop: [ALL]" in compose
    assert "no-new-privileges:true" in compose
    assert "3306:3306" not in compose


def test_metor_overlay_uses_http_boundary_and_no_ai_volumes() -> None:
    overlay = read(DEPLOYMENT / "compose.metor.yaml")
    metor_section = overlay.split("  metor:", maxsplit=1)[1]
    assert "AI_BASE_URL: http://ai-runtime:8090" in metor_section
    assert "condition: service_healthy" in metor_section
    assert "metor-data:/data/metor" in metor_section
    assert "ai-documents" not in metor_section
    assert "ai-chroma" not in metor_section
    assert "/models/embedding" not in metor_section



def test_operational_scripts_have_valid_shell_syntax() -> None:
    for path in sorted((DEPLOYMENT / "scripts").glob("*.sh")):
        shell = "bash" if "bash" in read(path).splitlines()[0] else "sh"
        subprocess.run([shell, "-n", str(path)], check=True)


def test_runbooks_and_bundle_contract_exist() -> None:
    required = [
        DEPLOYMENT / ".env.full-local.example",
        DEPLOYMENT / "README.md",
        DEPLOYMENT / "docs/offline-deployment.md",
        DEPLOYMENT / "docs/backup-restore.md",
        DEPLOYMENT / "docs/troubleshooting.md",
    ]
    assert all(path.is_file() and path.stat().st_size > 0 for path in required)
    bundle_script = read(DEPLOYMENT / "scripts/local-stack.py")
    assert '"docker", "save"' in bundle_script
    assert "SHA256SUMS" in bundle_script
    assert 'DEPLOYMENT / "docs"' in bundle_script


def test_docker_archive_platform_validation(tmp_path: Path) -> None:
    checker = DEPLOYMENT / "scripts/inspect-docker-archive.py"
    for architecture, include_layer, expected_code in (
        ("amd64", True, 0),
        ("arm64", True, 1),
        ("amd64", False, 1),
    ):
        path = tmp_path / f"{architecture}-{include_layer}.tar"
        files = {
            "manifest.json": json.dumps(
                [{"Config": "config.json", "Layers": ["layer.tar"], "RepoTags": ["fixture:1"]}]
            ).encode(),
            "config.json": json.dumps({"os": "linux", "architecture": architecture}).encode(),
        }
        if include_layer:
            files["layer.tar"] = b"fixture"
        with tarfile.open(path, "w") as archive:
            for name, data in files.items():
                member = tarfile.TarInfo(name)
                member.size = len(data)
                archive.addfile(member, io.BytesIO(data))
        result = subprocess.run([sys.executable, str(checker), str(path)], capture_output=True)
        assert result.returncode == expected_code


def test_amd64_build_does_not_load_or_run_images() -> None:
    script = read(DEPLOYMENT / "scripts/build-amd64-images.sh")
    assert "--driver docker-container" in script
    assert "--platform linux/amd64" in script
    assert "type=docker,dest=" in script
    assert "--load" not in script
    assert "docker load" not in script
    assert "docker run" not in script


def test_license_mounts_survive_all_volume_overrides() -> None:
    ai_paths = ["compose.ai.yaml", "compose.full-local.yaml", "compose.shared-runtime.yaml"]
    for name in ai_paths:
        text = read(DEPLOYMENT / name)
        ai = text.split("  ai-runtime:", 1)[1].split("  metor:", 1)[0]
        assert "target: /run/icp-license/identity" in ai
        assert "target: /run/icp-license/shared" in ai
        assert "target: /run/icp-license/state/ai" in ai
        assert "target: /run/icp-license/state/metor" not in ai
        assert "create_host_path: false" in ai
        shared = ai.split("target: /run/icp-license/shared", 1)[1]
        assert "read_only: true" in shared.split("- type: bind", 1)[0]
    for name in ["compose.metor.yaml", "compose.shared-runtime.yaml"]:
        metor = read(DEPLOYMENT / name).split("  metor:", 1)[1]
        assert "target: /run/icp-license/state/metor" in metor
        assert "target: /run/icp-license/state/ai" not in metor
    overlay = read(DEPLOYMENT / "compose.license-host.yaml")
    assert overlay.count("target: /run/icp-host/machine-id") == 2
    assert "create_host_path: false" in overlay


def test_numeric_runtime_users_and_separate_customer_build_metadata() -> None:
    java = read(REPO_ROOT / "metor-service/Dockerfile")
    python = read(REPO_ROOT / "ai-runtime-service/Dockerfile")
    assert "--gid 21000 license-runtime" in java
    assert "--uid 21001 --gid 21001 --groups license-runtime" in java
    assert "--uid 21002 --gid 21002 --groups license-runtime" in python
    assert "LICENSE_RELEASE_MODE=CUSTOMER_REQUIRED" in python
    assert "build_license_metadata.py" in python
    assert "USER metor" in java and "USER ai-runtime" in python
