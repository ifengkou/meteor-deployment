"""Verify fixed SDK release inputs and the licensing resources in customer images."""

import base64
import hashlib
import json
import re
import tarfile
import tempfile
import zipfile
from pathlib import Path

SDK_VERSION = "0.7.1"
RELEASE_SHA256 = {
    "metor_license_core-0.7.1-py3-none-any.whl": "f12c31d872ee3cc93d8683d074a32cd62d8b973e9b771bc9a5b98363384c15e4",
    "license-core-0.7.1.jar": "968f77ab25d5cb9cbb9a403db57549caddca2db669850d7efcbfc8248e443dd7",
    "license-sdk-java-maven-0.7.1.tar.gz": "c1e51eb24109ffaff6096482876036b3fde080def747591e752df0719cf6a77a",
}


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def verify_input(path, name):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or sha256(path.read_bytes()) != RELEASE_SHA256[name]:
        raise ValueError(f"SDK Release input checksum mismatch: {name}")


def verify_build_inputs(workspace, relative="license-build/license-product.json"):
    relative = Path(relative)
    if relative.is_absolute() or ".." in relative.parts or relative.parts[:1] != ("license-build",):
        raise ValueError("public product configuration must be inside each license-build directory")
    roots = [Path(workspace) / name for name in ("ai-runtime-service", "metor-service")]
    raw = []
    for root in roots:
        path = root / relative
        if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= 65536:
            raise ValueError("prepare the same Issuer public configuration in both license-build directories")
        raw.append(path.read_bytes())
    if raw[0] != raw[1]:
        raise ValueError("Java and Python public product configuration raw bytes differ")
    verify_input(roots[0] / "wheelhouse/metor_license_core-0.7.1-py3-none-any.whl",
                 "metor_license_core-0.7.1-py3-none-any.whl")
    verify_input(roots[1] / "vendor/license-maven/io/metor/license/license-core/0.7.1/license-core-0.7.1.jar",
                 "license-core-0.7.1.jar")
    return sha256(raw[0])


def validate_resources(metadata, raw, routes):
    if (set(metadata) != {"schema_version", "mode", "api_routes_sha256", "product_config_sha256"}
            or type(metadata["schema_version"]) is not int or metadata["schema_version"] != 2
            or metadata["mode"] != "CUSTOMER_REQUIRED"
            or not 0 < len(raw) <= 65536 or not 0 < len(routes) <= 65536
            or metadata["product_config_sha256"] != sha256(raw)
            or metadata["api_routes_sha256"] != sha256(routes)):
        raise ValueError("customer image licensing metadata/configuration/routes mismatch")
    config = json.loads(raw)
    keys = config.get("trusted_keys", {})
    if (config.get("product_id") != "icp-diag"
            or {service["id"] for service in config.get("services", [])} != {"metor", "ai"}
            or not keys or any(re.search(r"test|synthetic|demo", key, re.I) for key in keys)
            or any("/j0dBPYQkArICHJgVExjdbW0D7TiOUkmIkQlttK3h8I=" in key for key in keys.values())):
        raise ValueError("customer image must contain the reviewed ICP vendor configuration")


def inspect_boot_jar(path):
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError("duplicate BootJar resources")
        libraries = [name for name in names if name.startswith("BOOT-INF/lib/license-core-")]
        expected = f"BOOT-INF/lib/license-core-{SDK_VERSION}.jar"
        if libraries != [expected] or sha256(archive.read(expected)) != RELEASE_SHA256[f"license-core-{SDK_VERSION}.jar"]:
            raise ValueError("BootJar does not contain the approved SDK release")
        raw = archive.read("META-INF/license-product.json")
        metadata = json.loads(archive.read("META-INF/metor-license-release.json"))
        validate_resources(metadata, raw, archive.read("META-INF/metor-license-routes.json"))
        return raw


# Run only the product's licensing factory, never the AI application or its business services.
# Compare every installed wheel payload byte with the approved original release wheel.
AI_PROBE = r'''
import base64, hashlib, importlib.metadata, json, pathlib, zipfile
from app.licensing import create_license_resource
assert importlib.metadata.version("metor-license-core") == "0.7.1"
distribution = importlib.metadata.distribution("metor-license-core")
assert len([d for d in importlib.metadata.distributions()
            if d.metadata["Name"].replace("_", "-") == "metor-license-core"]) == 1
with zipfile.ZipFile("/sdk-release.whl") as wheel:
    for name in wheel.namelist():
        if name.endswith("/") or name.endswith("/RECORD"):
            continue
        assert distribution.locate_file(name).read_bytes() == wheel.read(name), name
root = pathlib.Path("/nonexistent-license-release-probe")
resource = create_license_resource(root, root / "machine-id")
assert resource.runtime is not None and resource.policy.valid
resource.runtime.close()
print(json.dumps({name: base64.b64encode(pathlib.Path("/app/app", name).read_bytes()).decode()
                  for name in ("_license_build.json", "license-product.json", "license-routes.json")}))
'''


def inspect_images(run, ai_image, metor_image, wheel):
    """Inputs must be local immutable image IDs; return only public release metadata."""
    for image in (ai_image, metor_image):
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", image):
            raise ValueError("release verification requires immutable local image IDs")
    verify_input(wheel, f"metor_license_core-{SDK_VERSION}-py3-none-any.whl")
    output = run(["docker", "run", "--rm", "--pull=never", "--network=none", "--read-only",
                  "--mount", f"type=bind,src={Path(wheel).resolve()},dst=/sdk-release.whl,readonly",
                  "--entrypoint", "python", ai_image, "-c", AI_PROBE],
                 capture_output=True, text=True).stdout
    resources = {name: base64.b64decode(value, validate=True) for name, value in json.loads(output).items()}
    raw = resources["license-product.json"]
    validate_resources(json.loads(resources["_license_build.json"]), raw, resources["license-routes.json"])
    with tempfile.TemporaryDirectory(prefix="icp-release-") as folder:
        container = run(["docker", "create", "--network=none", "--entrypoint", "/bin/true", metor_image],
                        capture_output=True, text=True).stdout.strip()
        try:
            jar = Path(folder) / "app.jar"
            run(["docker", "cp", f"{container}:/app/app.jar", str(jar)])
            if inspect_boot_jar(jar) != raw:
                raise ValueError("Java and Python customer configurations differ in raw bytes")
        finally:
            run(["docker", "rm", container], capture_output=True, text=True)
    return {"sdkVersion": SDK_VERSION,
            "sdkRelease": f"https://github.com/ifengkou/license-sdk/releases/tag/v{SDK_VERSION}",
            "releaseArtifactsSha256": dict(RELEASE_SHA256),
            "productConfigSha256": sha256(raw), "mode": "CUSTOMER_REQUIRED"}


def archive_config_ids(path, records):
    """Hash the actual saved config bytes, the stable image identity in classic Docker."""
    found = {}
    with tarfile.open(path) as archive:
        manifests = json.load(archive.extractfile("manifest.json"))
        for entry in manifests:
            member = archive.getmember(entry["Config"])
            if not member.isfile() or member.size > 4 * 1024 * 1024:
                raise ValueError("regular bounded image configuration required")
            raw = archive.extractfile(member).read()
            configuration = json.loads(raw)
            for record in records:
                if record["reference"] in (entry.get("RepoTags") or []):
                    if record["reference"] in found or (
                            configuration.get("os"), configuration.get("architecture")) != (
                            record["os"], record["architecture"]):
                        raise ValueError("duplicate image reference or wrong saved configuration platform")
                    found[record["reference"]] = "sha256:" + sha256(raw)
    if set(found) != {record["reference"] for record in records}:
        raise ValueError("saved archive does not cover every release image configuration")
    return found


def verify_bundle(bundle, *, imported=False):
    bundle = Path(bundle)
    images = bundle / "images"
    archive = images / "full-stack.tar"
    checksums = bundle / "SHA256SUMS"
    if (images.is_symlink() or not images.is_dir()
            or {path.name for path in images.iterdir()} != {"full-stack.tar"}
            or archive.is_symlink() or not archive.is_file()
            or checksums.is_symlink() or not checksums.is_file()):
        raise ValueError("bundle requires only the regular images/full-stack.tar archive")
    archive_entries = 0
    for line in checksums.read_text().splitlines():
        digest, separator, name = line.partition("  ")
        if not separator or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise ValueError("invalid bundle SHA256SUMS record")
        if name == "images/full-stack.tar":
            archive_entries += 1
    if archive_entries != 1:
        raise ValueError("SHA256SUMS must cover images/full-stack.tar exactly once")
    manifest = json.loads((Path(bundle) / "manifest.json").read_text())
    if not isinstance(manifest, dict):
        raise ValueError("bundle manifest must be an object")
    licensing = manifest.get("licensing", {})
    records = manifest.get("images", [])
    if (not isinstance(licensing, dict) or not isinstance(records, list)
            or len(records) != 4 or any(not isinstance(entry, dict) for entry in records)):
        raise ValueError("bundle manifest requires licensing metadata and four image records")
    if (manifest.get("formatVersion") not in {1, 2} or len(records) != 4
            or licensing.get("sdkVersion") != SDK_VERSION
            or licensing.get("mode") != "CUSTOMER_REQUIRED"
            or licensing.get("releaseArtifactsSha256") != RELEASE_SHA256
            or re.fullmatch(r"[0-9a-f]{64}", str(licensing.get("productConfigSha256"))) is None
            or manifest.get("licenseToolsImage") != records[1].get("id")):
        raise ValueError("bundle lacks the approved SDK release/configuration/tools image manifest")
    platforms = {(entry.get("os"), entry.get("architecture")) for entry in records}
    if len(platforms) != 1 or next(iter(platforms)) not in {("linux", "amd64"), ("linux", "arm64")}:
        raise ValueError("bundle images must use one supported Linux platform")
    for entry in records:
        if re.fullmatch(r"sha256:[0-9a-f]{64}", str(entry.get("id"))) is None:
            raise ValueError("bundle requires immutable image IDs")
        if "configId" in entry and re.fullmatch(r"sha256:[0-9a-f]{64}", str(entry["configId"])) is None:
            raise ValueError("bundle requires immutable image configuration IDs")
    if manifest["formatVersion"] == 2:
        import customer_bundle

        customer_bundle.verify_contents(bundle, manifest)
    if imported:
        import license_container

        for entry in records:
            license_container.resolve_image(entry)
    return manifest


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--workspace", type=Path)
    group.add_argument("--verify-bundle", type=Path)
    group.add_argument("--verify-imported", type=Path)
    parser.add_argument("--product-config", default="license-build/license-product.json")
    args = parser.parse_args()
    if args.workspace is not None:
        print(verify_build_inputs(args.workspace, args.product_config))
    else:
        verify_bundle(args.verify_bundle or args.verify_imported, imported=args.verify_imported is not None)
        print("fixed SDK release, configuration and image manifest verified")
