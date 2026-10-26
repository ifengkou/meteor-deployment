"""One-shot init/check inside the pinned AI image; never start the AI application."""

import argparse
import hashlib
import json
import re
import sys
from importlib.metadata import version
from importlib.resources import files
from pathlib import Path

import license_files

SDK_VERSION = "0.7.1"


def load_product():
    # Lazy imports keep the host's tooling/tests independent of any SDK installation.
    if version("metor-license-core") != SDK_VERSION:
        raise ValueError(f"license tools require SDK {SDK_VERSION}; load the reviewed AI image")
    from license_sdk import ProductConfig, parse_json_object

    resources = files("app")
    metadata = parse_json_object(license_files.read_regular(Path(str(resources / "_license_build.json"))))
    raw = license_files.read_regular(Path(str(resources / "license-product.json")))
    digest = hashlib.sha256(raw).hexdigest()
    if (metadata.keys() != {"schema_version", "mode", "api_routes_sha256", "product_config_sha256"}
            or type(metadata["schema_version"]) is not int or metadata["schema_version"] != 2
            or metadata["mode"] != "CUSTOMER_REQUIRED"
            or not isinstance(metadata["api_routes_sha256"], str)
            or re.fullmatch(r"[0-9a-f]{64}", metadata["api_routes_sha256"]) is None
            or metadata["product_config_sha256"] != digest):
        raise ValueError("license tools require intact schema 2 customer build metadata/configuration")
    product = ProductConfig.from_bytes(raw)
    if (product.profile.product_id != "icp-diag"
            or {service for service, _ in product.profile.recovery_prefixes} != {"metor", "ai"}):
        raise ValueError("license tools require the reviewed ICP product and exactly metor/ai services")
    return product, digest


def run_operation(action, root=None):
    product, digest = load_product()
    if action == "probe":
        return {"sdk_version": SDK_VERSION, "product_config_sha256": digest}
    root = license_files.safe_path(root)
    if action == "check":
        from license_sdk.installation import validate_installation
        # No locks, init, Runtime, clock updates, permissions repair or commercial inspection.
        license_files.validate_layout(root)
        return {"installation_id": validate_installation(product, root), "state": "VALID"}
    from license_sdk.installation import initialize_installation

    license_files.reviewed_paths(root, draft=True)
    result = initialize_installation(product, root)
    try:
        license_files.apply_permissions(root)
    except (OSError, ValueError) as error:
        raise ValueError(
            "LICENSE_STORAGE_OUTCOME_UNKNOWN: SDK installation preserved; permissions/durability "
            "not confirmed, stop writers and retry the same license-init command"
        ) from error
    return {"installation_id": result.installation_id, "state": result.action_status}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("probe", "init", "check"))
    parser.add_argument("--root", type=Path)
    args = parser.parse_args()
    if args.action != "probe" and args.root is None:
        parser.error("--root is required for init/check")
    try:
        print(json.dumps(run_operation(args.action, args.root)))
    except (OSError, ValueError, ImportError) as error:
        print(f"License maintenance failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
