#!/usr/bin/env python3
"""Isolated product 0.6.0 -> 0.7.1 compatibility verification, never a customer installer.

Requires local, reviewed old/new customer images and an exported historical installer.
Only generated test trust resources are overlaid; application/SDK binaries remain the
ones extracted from those images. No existing Compose project or customer root is used.
Host dependencies: Python standard library, Docker, JDK 21 and an installed Issuer CLI.
"""

import argparse
import base64
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from datetime import datetime, timedelta, timezone
from uuid import uuid4
import zipfile

SDK_JAR_SHA = "968f77ab25d5cb9cbb9a403db57549caddca2db669850d7efcbfc8248e443dd7"
OLD_JAR_SHA = "691bbd26e0ae294591fbcfbbe09114dd6b9bbf97d421d3a7d3cd680aefd6baf0"
BASELINE_INIT_SHA = "39c0497e7ae70473679f2fecc2f0eb94d04904097eb62b2fbb7537c5ef57a24a"
DEPLOYMENT = Path(__file__).resolve().parents[1]
FIXTURES = DEPLOYMENT / "tests/fixtures/license_upgrade"
RUN_REPORT = None
REPORT_PATH = None


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def write_report(path, report, result):
    report["result"] = result
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2) + "\n")


def execute(args, *, json_result=False, cwd=None):
    result = subprocess.run(list(map(str, args)), cwd=cwd, capture_output=True, text=True)
    if result.returncode:
        # Probe output is controlled test metadata only. Never print signing inputs or files.
        raise RuntimeError(f"{args[0]} command failed ({result.returncode}): {result.stderr[-2000:]}")
    if not json_result:
        return result.stdout
    lines = [line for line in result.stdout.splitlines() if line.startswith("{")]
    if not lines:
        raise ValueError("probe returned no JSON result")
    return json.loads(lines[-1])


def image_info(image, platform):
    info = json.loads(execute(["docker", "image", "inspect", image]))[0]
    if f"{info['Os']}/{info['Architecture']}" != platform:
        raise ValueError(f"image {image} does not match requested {platform}")
    return {"id": info["Id"], "platform": platform, "repo_digests": info.get("RepoDigests", [])}


def copy_from_image(image, source, target):
    name = "icp-sdk-upgrade-extract-" + uuid4().hex
    execute(["docker", "create", "--name", name, "--entrypoint", "/bin/true", image])
    try:
        execute(["docker", "cp", f"{name}:{source}", target])
    finally:
        execute(["docker", "rm", name])


def patch_jar(source, target, public_config, der):
    """Change test trust resources only, retaining ZipInfo/storage of all binaries."""
    with zipfile.ZipFile(source) as original, zipfile.ZipFile(target, "w") as output:
        names = original.namelist()
        if len(names) != len(set(names)):
            raise ValueError("duplicate entries in baseline/product BootJar")
        metadata_name = "META-INF/metor-license-release.json"
        metadata = json.loads(original.read(metadata_name))
        sdk_names = [name for name in names if name.startswith("BOOT-INF/lib/license-core-")]
        if len(sdk_names) != 1:
            raise ValueError("BootJar must contain exactly one SDK")
        expected = OLD_JAR_SHA if metadata["schema_version"] == 1 else SDK_JAR_SHA
        if digest(original.read(sdk_names[0])) != expected:
            raise ValueError("BootJar SDK does not match the reviewed Release")
        if metadata["schema_version"] == 1:
            metadata["trusted_keys"] = {"upgrade-2026": der}
            metadata["trust_version"] = "upgrade-2026"
        elif metadata["schema_version"] == 2:
            metadata["product_config_sha256"] = digest(public_config)
        else:
            raise ValueError("unexpected product metadata schema")
        for item in original.infolist():
            raw = original.read(item)
            if item.filename == metadata_name:
                raw = json.dumps(metadata).encode()
            elif item.filename == "META-INF/license-product.json":
                raw = public_config
            output.writestr(item, raw)
    return {"sdk_sha256": expected, "original_boot_jar_sha256": digest(source.read_bytes())}


def extract_classpath(jar, directory):
    directory.mkdir()
    with zipfile.ZipFile(jar) as archive:
        for item in archive.infolist():
            if item.filename.startswith(("BOOT-INF/classes/", "BOOT-INF/lib/")):
                path = directory / item.filename
                if ".." in Path(item.filename).parts or Path(item.filename).is_absolute():
                    raise ValueError("unsafe BootJar path")
                if item.is_dir():
                    path.mkdir(parents=True, exist_ok=True)
                else:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(archive.read(item))


def main():
    global RUN_REPORT, REPORT_PATH
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, help="Optional isolated env containing AI_RUNTIME_IMAGE and METOR_IMAGE")
    parser.add_argument("--baseline-ai-image", required=True)
    parser.add_argument("--baseline-metor-image", required=True)
    parser.add_argument("--ai-image")
    parser.add_argument("--metor-image")
    parser.add_argument("--baseline-initializer", required=True, type=Path,
                        help="Unmodified historical deployment/scripts/license_init.py; archived input only")
    parser.add_argument("--issuer-python", required=True, type=Path,
                        help="Python interpreter with the real license-issuer CLI installed")
    parser.add_argument("--javac", default="javac")
    parser.add_argument("--platform", default="linux/amd64", choices=("linux/amd64", "linux/arm64"))
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    RUN_REPORT = {"platform": args.platform, "checks": [], "manual_customer_acceptance": "PENDING"}
    REPORT_PATH = args.report
    write_report(REPORT_PATH, RUN_REPORT, "RUNNING")
    values = {}
    if args.env_file:
        for line in args.env_file.read_text().splitlines():
            if line.strip() and not line.lstrip().startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip().strip("\"'")
    images = {
        "old_ai": args.baseline_ai_image, "old_metor": args.baseline_metor_image,
        "new_ai": args.ai_image or values.get("AI_RUNTIME_IMAGE"),
        "new_metor": args.metor_image or values.get("METOR_IMAGE"),
    }
    if not all(images.values()):
        parser.error("provide both new images with flags or the isolated env file")
    if digest(args.baseline_initializer.read_bytes()) != BASELINE_INIT_SHA:
        parser.error("baseline initializer must be the unmodified deployment 240b21a artifact")
    info = {role: image_info(image, args.platform) for role, image in images.items()}
    images = {role: row["id"] for role, row in info.items()}
    report = {"platform": args.platform, "amd64_automated_run": args.platform == "linux/amd64",
              "manual_customer_acceptance": "PENDING",
              "test_only_trust_overlay": True, "images": info,
              "baseline_initializer_sha256": digest(args.baseline_initializer.read_bytes()), "checks": []}
    report["driver_sha256"] = digest(Path(__file__).read_bytes())
    report["fixture_sha256"] = {path.name: digest(path.read_bytes()) for path in FIXTURES.iterdir() if path.is_file()}
    report["source_repositories"] = {}
    for name in ("deployment", "metor-service", "ai-runtime-service"):
        root = DEPLOYMENT.parent / name
        if (root / ".git").exists():
            report["source_repositories"][name] = {
                "head": execute(["git", "rev-parse", "HEAD"], cwd=root).strip(),
                "dirty": bool(execute(["git", "status", "--porcelain"], cwd=root).strip()),
            }
    RUN_REPORT, REPORT_PATH = report, args.report
    write_report(args.report, report, "RUNNING")
    checks = report["checks"]
    volume = "icp-sdk-upgrade-" + uuid4().hex
    with tempfile.TemporaryDirectory(prefix="icp-sdk-upgrade-") as temporary:
        work = Path(temporary).resolve()
        work.chmod(0o755)
        for path in FIXTURES.iterdir():
            if path.is_file():
                shutil.copyfile(path, work / path.name)
        for name in ("license_init.py", "license_files.py", "license_backup.py"):
            shutil.copyfile(DEPLOYMENT / "scripts" / name, work / name)
        shutil.copyfile(args.baseline_initializer, work / "baseline-initializer.py")
        (work / "machine-id").write_text("0123456789abcdef0123456789abcdef\n")
        (work / "other-machine-id").write_text("abcdef0123456789abcdef0123456789\n")
        password = work / "passphrase"
        password.write_bytes(os.urandom(32).hex().encode())
        password.chmod(0o600)

        def issuer(*command):
            return execute([args.issuer_python, "-c", "from license_issuer.cli import main; raise SystemExit(main())", *command], json_result=True)

        issuer("keygen", "--key-id", "upgrade-2026", "--private-key", work / "private.pem",
               "--public-key", work / "public.pem", "--passphrase-file", password)
        pem = (work / "public.pem").read_text()
        der = "".join(line for line in pem.splitlines() if not line.startswith("---"))
        base64.b64decode(der, validate=True)
        copy_from_image(images["new_ai"], "/app/app/license-product.json", work / "provided-product.json")
        product = json.loads((work / "provided-product.json").read_bytes())
        product["trusted_keys"] = {"upgrade-2026": pem}
        public_raw = json.dumps(product, sort_keys=True, separators=(",", ":")).encode()
        (work / "license-product.json").write_bytes(public_raw)
        report["provided_product_config_sha256"] = digest((work / "provided-product.json").read_bytes())
        report["fixture_product_config_sha256"] = digest(public_raw)
        for role in ("old_ai", "new_ai"):
            path = work / (role + "-metadata.json")
            copy_from_image(images[role], "/app/app/_license_build.json", path)
            metadata = json.loads(path.read_bytes())
            if role == "old_ai":
                if metadata["schema_version"] != 1:
                    raise ValueError("baseline AI is not the expected old product")
                metadata["trusted_keys"] = {"upgrade-2026": der}
                metadata["trust_version"] = "upgrade-2026"
            else:
                if metadata["schema_version"] != 2:
                    raise ValueError("new AI is not the expected new product")
                metadata["product_config_sha256"] = digest(public_raw)
            path.write_text(json.dumps(metadata))
        for role in ("old_metor", "new_metor"):
            original, patched = work / (role + "-original.jar"), work / (role + ".jar")
            copy_from_image(images[role], "/app/app.jar", original)
            report[role] = patch_jar(original, patched, public_raw, der)
            extract_classpath(patched, work / role)
        execute([args.javac, "--release", "21", "-d", work, work / "MetorUpgradeProbe.java"])
        config = {key: product[key] for key in ("product_id", "fingerprint_domain", "binding_domain", "recovery_domain", "request_prefix")}
        config.update(key_id="upgrade-2026", private_key=str(work / "private.pem"),
                      public_key=str(work / "public.pem"), records_dir=str(work), output_dir=str(work))
        toml = "\n".join(f"{key} = {json.dumps(value)}" for key, value in config.items())
        for service in product["services"]:
            toml += "\n\n[[services]]\n" + "\n".join(f"{key} = {json.dumps(value)}" for key, value in service.items())
        (work / "issuer.toml").write_text(toml + "\n")
        now = datetime.now(timezone.utc).replace(microsecond=0)
        utc = lambda value: value.strftime("%Y-%m-%dT%H:%M:%SZ")

        def container(role, command, *, case=None, service=None, readonly=False, machine="machine-id", extra=()):
            cmd = ["docker", "run", "--rm", "--pull=never", "--network=none", "--platform", args.platform,
                   "--cap-drop=ALL", "--security-opt=no-new-privileges", "--user", "0:0" if service is None else f"{21001 if service == 'metor' else 21002}:{21001 if service == 'metor' else 21002}",
                   "--mount", f"type=bind,src={work},dst=/probe,readonly"]
            if service:
                cmd += ["--group-add", "21000", "--mount", f"type=volume,src={volume},dst=/license,volume-subpath={case},readonly"]
                if not readonly:
                    cmd += ["--mount", f"type=volume,src={volume},dst=/license/state/{service},volume-subpath={case}/state/{service}"]
                    if service == "metor":
                        cmd += ["--mount", f"type=volume,src={volume},dst=/license/shared,volume-subpath={case}/shared"]
            else:
                cmd += ["--cap-add=DAC_OVERRIDE"]
                if not readonly:
                    cmd += ["--cap-add=CHOWN", "--cap-add=FOWNER"]
                cmd += ["--mount", f"type=volume,src={volume},dst=/fixtures" + (",readonly" if readonly else "")]
            if role.endswith("ai"):
                cmd += ["--env", "PYTHONPATH=/app:/probe"]
                cmd += ["--mount", f"type=bind,src={work}/{role}-metadata.json,dst=/app/app/_license_build.json,readonly"]
                if role == "new_ai":
                    cmd += ["--mount", f"type=bind,src={work}/license-product.json,dst=/app/app/license-product.json,readonly"]
                cmd += ["--entrypoint", "python", images[role], *command]
            else:
                cp = f"/probe:/probe/{role}.jar:/probe/{role}/BOOT-INF/classes:/probe/{role}/BOOT-INF/lib/*"
                cmd += ["--entrypoint", "java", images[role], "-cp", cp, "io.metor.platform.license.MetorUpgradeProbe", *command]
            return execute(cmd + list(extra), json_result=True)

        def files(action, case, *rest, readonly=False):
            return container("old_ai", ["/probe/files_probe.py", action, case, *rest], readonly=readonly)

        def probe(role, action, case, file=None, machine="machine-id", readonly=False):
            service = "ai" if role.endswith("ai") else "metor"
            command = (["/probe/ai_probe.py"] if service == "ai" else []) + [action, "/probe/" + machine]
            if file:
                command.append("/probe/" + file)
            result = container(role, command, case=case, service=service, readonly=readonly)
            if service == "ai" and result["sdk_version"] != ("0.6.0" if role.startswith("old") else "0.7.1"):
                raise AssertionError("incorrect installed AI SDK")
            return result

        def active(role, case, expected="ACTIVE", **kwargs):
            result = probe(role, "status", case, **kwargs)
            if result.get("state") != expected or result.get("allowed") != (expected == "ACTIVE"):
                raise AssertionError(f"{role}/{case}: expected {expected}, got {result}")

        def sign(name, binding, validity, request=None, *, start=None, end=None, issuer_config="issuer.toml"):
            command = ["sign-license", "--config", work / issuer_config, "--passphrase-file", password,
                       "--customer-id", "isolated-upgrade", "--customer-name", "Isolated upgrade fixture",
                       "--binding", binding, "--validity", validity,
                       "--not-before", utc(start or now - timedelta(days=1)), "--output", work / name]
            if validity == "TERM":
                command += ["--expires-at", utc(end or now + timedelta(days=365))]
            if binding == "HOST_INSTALL":
                (work / "request.json").write_text(json.dumps(request))
                command += ["--request-file", work / "request.json"]
            issuer(*command)

        execute(["docker", "volume", "create", volume])
        try:
            files("init", "base")
            active("old_ai", "base", "UNLICENSED")
            active("old_metor", "base", "UNLICENSED")
            request = probe("old_metor", "request", "base")
            for binding in ("HOST_INSTALL", "UNBOUND"):
                for validity in ("TERM", "PERPETUAL"):
                    case = binding + "-" + validity
                    files("copy", case, "base")
                    license_name = case + ".json"
                    sign(license_name, binding, validity, request)
                    imported = probe("old_metor", "import", case, license_name)
                    if imported.get("actionStatus") != "APPLIED":
                        raise AssertionError(imported)
                    before = files("snapshot", case, readonly=True)
                    # The real SDK readonly checker is used on a genuinely read-only root.
                    try:
                        checked = container("new_ai", ["-c", "from pathlib import Path; import json,license_init; print(json.dumps(license_init.run_operation('check', Path('/fixtures/" + case + "'))))"], readonly=True)
                    except RuntimeError as error:
                        raise ValueError("new check rejected isolated baseline paths: " + str(files("paths", case, readonly=True)["paths"])) from error
                    if before != files("snapshot", case, readonly=True) or not checked["installation_id"]:
                        raise AssertionError("upgrade check changed original bytes or permissions")
                    for role in images:
                        active(role, case)
                    repeated = probe("new_metor", "import", case, license_name)
                    if repeated.get("actionStatus") != "ALREADY_APPLIED":
                        raise AssertionError(repeated)
                    checks.append("commercial/" + case)
                    print("PASS commercial/" + case, flush=True)
            case = "UNBOUND-PERPETUAL"
            for role in ("new_ai", "new_metor"):
                active(role, case, machine="missing-machine-id")
            checks.append("unbound-without-machine-id")
            for role in ("new_ai", "new_metor"):
                active(role, "HOST_INSTALL-PERPETUAL", "INVALID", machine="other-machine-id")
            checks.append("host-binding-rejects-other-machine")
            before = files("snapshot", case, readonly=True)
            backup = container("new_ai", ["-c", "from pathlib import Path; import json,license_init,license_backup; "
                               "check=lambda root:license_init.run_operation('check',root)['installation_id']; "
                               "root=Path('/fixtures/UNBOUND-PERPETUAL'); target=Path('/fixtures/restored'); "
                               "archive=Path('/fixtures/license-state.tar.gz'); "
                               "metadata=license_backup.backup(root,archive,'isolated-host-sha',check); "
                               "stage=license_backup.prepare_restore(target,archive,metadata,'isolated-host-sha',check); "
                               "license_backup.publish_restore(target,stage); print(json.dumps(metadata))"])
            if set(backup) != {"archive", "installationId", "machineIdSha256"} or before != files("snapshot", "restored", readonly=True):
                raise AssertionError("new stopped backup/restore did not preserve original old installation")
            checks.append("new-tools-backup-restore-old-installation-exact-bytes-permissions")
            # Candidate validation belongs to the product's SDK transaction, before replacement.
            (work / "damaged.json").write_bytes(b"damaged")
            (work / "oversize.json").write_bytes(b"x" * 65537)
            # Adversarial files start from real Issuer output. Change fixture-only payloads,
            # then sign with our generated test key; production code never sees this helper.
            sign("valid-negative-base.json", "UNBOUND", "TERM")
            def altered(name, changes):
                execute([args.issuer_python, "-c", "import base64,json,sys; from pathlib import Path; from cryptography.hazmat.primitives import serialization; "
                         "p=Path(sys.argv[1]); e=json.loads((p/'valid-negative-base.json').read_bytes()); b=e['payload']; "
                         "v=json.loads(base64.urlsafe_b64decode(b+'='*(-len(b)%4))); v.update(json.loads(sys.argv[3])); "
                         "raw=json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode(); "
                         "k=serialization.load_pem_private_key((p/'private.pem').read_bytes(),(p/'passphrase').read_bytes()); "
                         "enc=lambda x:base64.urlsafe_b64encode(x).decode().rstrip('='); "
                         "(p/sys.argv[2]).write_text(json.dumps({'payload':enc(raw),'signature':enc(k.sign(raw))}))",
                         work, name, json.dumps(changes)])
            altered("expired.json", {"issued_at": utc(now-timedelta(days=4)), "not_before": utc(now-timedelta(days=3)), "expires_at": utc(now-timedelta(days=2))})
            altered("wrong-product.json", {"product_id": "other-product"})
            altered("wrong-key.json", {"key_id": "unknown-2026"})
            sign("future.json", "UNBOUND", "TERM", start=now+timedelta(days=3))
            for name, state in (("damaged.json", "INVALID"), ("oversize.json", "INVALID"),
                                ("expired.json", "EXPIRED"), ("future.json", "NOT_YET_VALID"),
                                ("wrong-product.json", "INVALID"), ("wrong-key.json", "INVALID")):
                before = files("snapshot", case, readonly=True)["shared/active.license.json"]
                rejected = probe("new_metor", "import", case, name)
                if "error" not in rejected or before != files("snapshot", case, readonly=True)["shared/active.license.json"]:
                    raise AssertionError("invalid candidate replaced the old file")
                files("copy", "error-" + name, case)
                files("commercial", "error-" + name, "/probe/" + name)
                for role in ("new_ai", "new_metor"):
                    active(role, "error-" + name, state)
                checks.append("rejection/" + name)
            for service in ("metor", "ai"):
                permissions = container("new_ai", ["/probe/files_probe.py", "permissions", "."], case=case, service=service)
                if not permissions.get("state_isolation") or permissions.get("uid") != (21001 if service == "metor" else 21002):
                    raise AssertionError(permissions)
            checks.append("numeric-uid-gid-state-and-readonly-mounts")
            # No request traffic: two independent SDK-owned workers advance only their clocks.
            before = files("snapshot", case, readonly=True)
            clocks = {service: files("clock", case, service, readonly=True) for service in ("metor", "ai")}
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda role: probe(role, "worker", case), ("new_ai", "new_metor")))
            if any(result.get("state") != "ACTIVE" for result in results):
                raise AssertionError(results)
            after = files("snapshot", case, readonly=True)
            for name in ("identity/installation.json", "identity/service.key", "shared/active.license.json"):
                if before[name] != after[name]:
                    raise AssertionError("normal migration changed stable identity or commercial bytes")
            for service in ("metor", "ai"):
                current = files("clock", case, service, readonly=True)
                if current["sequence"] <= clocks[service]["sequence"]:
                    raise AssertionError("SDK worker did not checkpoint without requests")
            latest = {service: files("clock", case, service, readonly=True) for service in ("metor", "ai")}
            for role in ("old_ai", "old_metor"):
                active(role, case)
            if latest != {service: files("clock", case, service, readonly=True) for service in ("metor", "ai")}:
                raise AssertionError("rollback changed epoch/sequence/high-watermark")
            checks.append("workers-and-latest-state-rollback")
            for service, damage in ((service, damage) for service in ("metor", "ai") for damage in ("rollback", "broken", "missing")):
                recovery_case = "recovery-" + service + "-" + damage
                files("copy", recovery_case, case)
                files(damage, recovery_case, service)
                old_role, new_role = "old_" + service, "new_" + service
                active(new_role, recovery_case, "CLOCK_ROLLBACK" if damage == "rollback" else "CLOCK_STATE_INVALID")
                challenge = probe(old_role, "recovery-request", recovery_case)
                before = files("snapshot", recovery_case, readonly=True)
                new_challenge = probe(new_role, "recovery-request", recovery_case)
                if {key: value for key, value in challenge.items() if key != "sdk_version"} != {key: value for key, value in new_challenge.items() if key != "sdk_version"}:
                    raise AssertionError("new runtime did not preserve the old challenge")
                request_path = work / (recovery_case + "-request.json")
                request_path.write_text(json.dumps({key: value for key, value in challenge.items() if key != "sdk_version"}))
                output = recovery_case + ".json"
                window = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(seconds=3)
                issuer("sign-recovery", "--config", work / "issuer.toml", "--passphrase-file", password,
                       "--request-file", request_path, "--window-start", utc(window),
                       "--window-end", utc(window+timedelta(days=6)), "--output", work / output)
                remaining = (window - datetime.now(timezone.utc)).total_seconds() + 0.1
                if remaining > 0:
                    time.sleep(remaining)
                result = probe(new_role, "recover", recovery_case, output)
                if (result.get("actionStatus"), result.get("repeatStatus"), result.get("state"), result.get("refreshedState")) != ("APPLIED", "ALREADY_APPLIED", "ACTIVE", "ACTIVE"):
                    raise AssertionError(result)
                restarted = probe(new_role, "recover", recovery_case, output)
                if restarted.get("actionStatus") != "ALREADY_APPLIED":
                    raise AssertionError(restarted)
                after = files("snapshot", recovery_case, readonly=True)
                other = "ai" if service == "metor" else "metor"
                for name in ("identity/installation.json", "identity/service.key", "shared/active.license.json", f"state/{other}/clock.json"):
                    if before[name] != after[name]:
                        raise AssertionError("recovery changed another service/identity/commercial file")
                latest = files("clock", recovery_case, service, readonly=True)
                active(old_role, recovery_case)
                if latest != files("clock", recovery_case, service, readonly=True):
                    raise AssertionError("rollback after recovery changed the latest high-watermark")
                checks.append("old-challenge-recovery/" + service + "/" + damage)
                print("PASS old-challenge-recovery/" + service + "/" + damage, flush=True)
        finally:
            execute(["docker", "volume", "rm", volume])
    write_report(args.report, report, "PASS")
    print(json.dumps({"result": "PASS", "platform": args.platform, "checks": len(checks), "report": str(args.report)}))


if __name__ == "__main__":
    try:
        main()
    except BaseException as error:
        if RUN_REPORT is not None and (not isinstance(error, SystemExit) or error.code):
            RUN_REPORT["failure_type"] = type(error).__name__
            write_report(REPORT_PATH, RUN_REPORT, "FAIL")
        raise
