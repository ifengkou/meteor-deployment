#!/usr/bin/env python3
"""Protected, reproducible local deployment; never operates on the old AI volumes."""

import argparse
import hashlib
import json
import os
import platform
import re
import secrets
import shlex
import shutil
import subprocess
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path

DEPLOYMENT = Path(__file__).resolve().parents[1]


def deployment_layout(deployment):
    """Deployment is a sibling repository; bundles need no service source trees."""
    parent = deployment.parent
    if all((parent / name / "Dockerfile").is_file()
           for name in ("ai-runtime-service", "metor-service", "frontend")):
        return parent / "ai-runtime-service", parent
    return parent, None


AI_ROOT, WORKSPACE = deployment_layout(DEPLOYMENT)
RUNTIME_ROOT = WORKSPACE / "runtime" if WORKSPACE else AI_ROOT / "runtime"
DEFAULT_ENV = RUNTIME_ROOT / "config/docker.env"
DEFAULT_CATALOG = DEPLOYMENT / "config/embedding-models.example.json"
PROJECT = "icp-diag-local"
ALLOWED_PROJECTS = ("icp-diag-local", "icp-diag-local-restore-check")
FILES = ["compose.ai.yaml", "compose.metor.yaml", "compose.full-local.yaml"]


def file_sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(command, **kwargs):
    return subprocess.run(command, check=True, **kwargs)


def read_env(path):
    result = {}
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, value = line.removeprefix("export ").split("=", 1)
        # Parse quotes without executing shell code or expanding secrets.
        values = shlex.split(value, comments=True)
        result[key.strip()] = values[0] if values else ""
    return result


def compose(env_file, *args, **kwargs):
    if PROJECT not in ALLOWED_PROJECTS:
        raise ValueError("unsupported local deployment project")
    if not env_file.is_file():
        raise ValueError("run init before using the local stack")
    if env_file.stat().st_mode & 0o077:
        raise ValueError("environment file must have mode 0600")
    config = read_env(env_file)
    if config.get("METOR_DATABASE") != "metor_service":
        raise ValueError("local stack only accepts target database metor_service")
    command = ["docker", "compose", "-p", PROJECT, "--env-file", str(env_file)]
    files = [*FILES]
    if config.get("WORKSPACE_RUNTIME_DIR"):
        files.append("compose.shared-runtime.yaml")
    host_identity = Path(config.get("LICENSE_MACHINE_ID_PATH", "/etc/machine-id"))
    if host_identity.is_file():
        files.append("compose.license-host.yaml")
    for name in files:
        command.extend(["-f", str(DEPLOYMENT / name)])
    return run(command + list(args), **kwargs)


def mysql(env_file, sql, database=None):
    if database:
        if database not in ("metor_service", "metor_ai"):
            raise ValueError("unsupported target business database")
        # Import with the schema-specific account, so qualified SQL cannot write
        # another business/system database even if textual validation misses it.
        command = (
            'if [ "$1" = metor_service ]; then '
            'MYSQL_PWD="$METOR_DB_PASSWORD" exec mysql -u"$METOR_DB_USER" --batch "$1"; '
            'else MYSQL_PWD="$MYSQL_PASSWORD" exec mysql -u"$MYSQL_USER" --batch "$1"; fi'
        )
        args = ["exec", "-T", "mysql", "sh", "-c", command, "mysql", database]
    else:
        args = [
            "exec",
            "-T",
            "mysql",
            "sh",
            "-c",
            'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot --batch --skip-column-names',
            "mysql",
        ]
    return compose(env_file, *args, input=sql, capture_output=True).stdout


def init(args):
    if args.env_file.exists():
        raise ValueError(
            "environment file already exists; preserve it instead of regenerating credentials"
        )
    model_path = args.model_path.resolve()
    if not (model_path / "config.json").is_file():
        raise ValueError("model path must contain an existing Hugging Face model config.json")
    catalog_source = args.catalog.resolve()
    catalog = json.loads(catalog_source.read_text())
    if catalog_source == DEFAULT_CATALOG.resolve():
        for model in catalog["models"]:
            if model.get("enabled", True) and model["id"] == "bge-small-zh-v1.5":
                model["modelPath"] = "/models/embedding"
    enabled = [m for m in catalog["models"] if m.get("enabled", True)]
    if not enabled or any(m["modelPath"] != "/models/embedding" for m in enabled):
        raise ValueError(
            "this local overlay supports enabled models at /models/embedding; map "
            "extra models explicitly before enabling them"
        )
    args.env_file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(args.env_file.parent, 0o700)
    catalog_target = args.env_file.parent / "embedding/docker.json"
    catalog_target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    catalog_target.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n")
    os.chmod(catalog_target, 0o644)
    ai_password = secrets.token_hex(24)
    jwt = secrets.token_hex(32)
    if args.metor_env_file:
        source = read_env(args.metor_env_file)
        jwt = source.get("METOR_PLATFORM_SECURITY_JWT_SECRET") or jwt
    values = {
        "TZ": "Asia/Shanghai",
        "MYSQL_IMAGE": "mysql:8.4",
        "AI_RUNTIME_IMAGE": "ai-runtime-service:p6-local",
        "METOR_IMAGE": "metor-service:p6-local",
        "FRONTEND_IMAGE": "metor-platform-frontend:p6-local",
        "METOR_PLATFORM": "linux/arm64"
        if platform.machine() in ("arm64", "aarch64")
        else "linux/amd64",
        "MYSQL_ROOT_PASSWORD": secrets.token_hex(24),
        "AI_DB_PASSWORD": ai_password,
        "AI_DB_URL": f"mysql+pymysql://ai_user:{ai_password}@mysql:3306/metor_ai?charset=utf8mb4",
        "METOR_DATABASE": "metor_service",
        "METOR_DB_USER": "metor_user",
        "METOR_DB_PASSWORD": secrets.token_hex(24),
        "METOR_PLATFORM_SECURITY_JWT_SECRET": jwt,
        "AI_EMBEDDING_MODEL_HOST_PATH": str(model_path),
        "AI_EMBEDDING_MODELS_CONFIG_HOST_PATH": str(catalog_target),
        "AI_RUNTIME_BIND_ADDRESS": "127.0.0.1",
        "AI_RUNTIME_EXPOSED_PORT": "18092",
        "METOR_BIND_ADDRESS": "127.0.0.1",
        "APP_EXPOSED_PORT": "18080",
        "FRONTEND_EXPOSED_PORT": "18180",
        "METOR_AEROSPACE_AI_ENABLED": "true",
    }
    fd = os.open(args.env_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w") as target:
        for key, value in values.items():
            target.write(f"{key}={shlex.quote(value)}\n")
    print(f"Protected configuration created: {args.env_file}")


def license_init(args):
    # Import only for this subcommand; no SDK, pip, machine-id or database required.
    import license_init as installer
    result = installer.initialize_license(args.license_root)
    print(json.dumps(result))


def validate_sql(sql, target):
    # Include MySQL executable-comment statements, not only ordinary DDL.
    normalized = re.sub(rb"/\*!\d*\s*", b"", sql)
    if re.search(
        rb"(?im)(?:^|;)\s*(?:CREATE\s+DATABASE|DROP\s+DATABASE|ALTER\s+DATABASE|USE\s+)", normalized
    ):
        raise ValueError(
            "dump contains database switching statements; export one database without --databases"
        )
    databases = (
        "phoenix",
        "metor_service",
        "metor_ai",
        "mysql",
        "sys",
        "information_schema",
        "performance_schema",
    )
    for database in databases:
        if database != target and re.search(
            rb"(?i)(?:`" + database.encode() + rb"`|\b" + database.encode() + rb"\b)\s*\.",
            normalized,
        ):
            raise ValueError(
                "dump contains a cross-database object; review qualified objects individually"
            )


def restore_metor(args):
    backup = args.backup.resolve()
    dump = backup / "phoenix.sql"
    if not dump.is_file():
        dump = backup / "metor_service.sql"
    if not dump.is_file():
        raise ValueError("backup must contain phoenix.sql or metor_service.sql")
    # Refuse SQL that can escape the selected target database. Do not blindly replace
    # occurrences in data values; rename any explicitly qualified objects individually.
    sql = dump.read_bytes()
    validate_sql(sql, "metor_service")
    if (
        mysql(
            args.env_file,
            b"SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='metor_service';\n",
        ).strip()
        != b"0"
    ):
        raise ValueError("restore refuses a nonempty metor_service; use a new target volume")
    states = compose(
        args.env_file, "ps", "--status", "running", "--services", capture_output=True, text=True
    ).stdout.splitlines()
    if "metor" in states:
        raise ValueError("stop only the target metor service before restoring")
    files = compose(
        args.env_file,
        "run",
        "--rm",
        "-T",
        "--no-deps",
        "--entrypoint",
        "sh",
        "metor",
        "-c",
        "find /data/metor -type f -print -quit",
        capture_output=True,
    ).stdout.strip()
    if files:
        raise ValueError("restore refuses an existing target Metor file volume")
    archive = backup / "metor-data.tar.gz"
    directory = backup / "metor-data"
    if not archive.is_file() and not directory.is_dir():
        raise ValueError("backup must include metor-data.tar.gz or metor-data/")
    # Check archives before importing any data: only relative regular files/directories.
    if archive.is_file():
        with tarfile.open(archive) as source:
            for item in source.getmembers():
                if (
                    item.name.startswith("/")
                    or ".." in Path(item.name).parts
                    or not (item.isfile() or item.isdir())
                ):
                    raise ValueError("unsafe path or nonregular entry in Metor data archive")
    mysql(args.env_file, sql, "metor_service")
    command = [
        "run",
        "--rm",
        "-T",
        "--no-deps",
        "--entrypoint",
        "sh",
        "metor",
        "-c",
        "tar --no-same-owner --no-same-permissions --no-overwrite-dir -C /data/metor -xf -",
    ]
    if archive.is_file():
        with subprocess.Popen(["gzip", "-dc", str(archive)], stdout=subprocess.PIPE) as unpack:
            compose(args.env_file, *command, stdin=unpack.stdout)
            if unpack.wait() != 0:
                raise ValueError("archive decompression failed")
    else:
        with subprocess.Popen(
            ["tar", "-C", str(directory), "-cf", "-", "."],
            stdout=subprocess.PIPE,
            env={**os.environ, "COPYFILE_DISABLE": "1"},
        ) as pack:
            compose(args.env_file, *command, stdin=pack.stdout)
            if pack.wait() != 0:
                raise ValueError("file archive creation failed")
    manifest = {
        "formatVersion": 1,
        "sourceDatabase": "phoenix",
        "targetDatabase": "metor_service",
        "sqlSha256": hashlib.sha256(sql).hexdigest(),
        "project": PROJECT,
        "restoredAt": datetime.now(timezone.utc).isoformat(),
        "aiDataImported": False,
    }
    report = args.env_file.parent / "restore-manifest.json"
    report.write_text(json.dumps(manifest, indent=2) + "\n")
    os.chmod(report, 0o600)
    print(
        "Metor database/files restored; run table counts, Flyway and readiness "
        "checks before opening traffic."
    )


def backup_stack(args):
    config = read_env(args.env_file)
    if config.get("WORKSPACE_RUNTIME_DIR"):
        ensure_native_services_stopped()
    target = args.backup.resolve()
    target.mkdir(parents=True, exist_ok=False, mode=0o700)
    running = compose(
        args.env_file, "ps", "--status", "running", "--services", capture_output=True, text=True
    ).stdout.splitlines()
    writers = [name for name in ("frontend", "metor", "ai-runtime") if name in running]
    try:
        if writers:
            compose(args.env_file, "stop", *writers)
        for database in ("metor_service", "metor_ai"):
            with (target / f"{database}.sql").open("wb") as output:
                compose(
                    args.env_file,
                    "exec",
                    "-T",
                    "mysql",
                    "sh",
                    "-c",
                    (
                        'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysqldump -uroot '
                        "--single-transaction --routines --triggers --events "
                        '--no-tablespaces --set-gtid-purged=OFF "$1"'
                    ),
                    "dump",
                    database,
                    stdout=output,
                )
        for service, container_path, name in [
            ("metor", "/data/metor", "metor-data.tar.gz"),
            ("ai-runtime", "/data/ai", "ai-data.tar.gz"),
        ]:
            with (target / name).open("wb") as output:
                compose(
                    args.env_file,
                    "run",
                    "--rm",
                    "-T",
                    "--no-deps",
                    "--entrypoint",
                    "tar",
                    service,
                    "-czf",
                    "-",
                    "-C",
                    container_path,
                    ".",
                    stdout=output,
                )
        shutil.copy2(args.env_file, target / "deployment.env")
        shutil.copy2(
            read_env(args.env_file)["AI_EMBEDDING_MODELS_CONFIG_HOST_PATH"],
            target / "embedding-models.json",
        )
        if config.get("WORKSPACE_RUNTIME_DIR"):
            shared_config = Path(config["WORKSPACE_RUNTIME_DIR"]) / "config"
            for source, name in (
                ("ai.local.env", "ai.local.env"),
                ("metor.local.env", "metor.local.env"),
                ("embedding/local.json", "embedding-local.json"),
            ):
                if (shared_config / source).is_file():
                    shutil.copy2(shared_config / source, target / name)
        (target / "backup-manifest.json").write_text(
            json.dumps(
                {
                    "formatVersion": 1,
                    "project": PROJECT,
                    "createdAt": datetime.now(timezone.utc).isoformat(),
                    "databases": ["metor_service", "metor_ai"],
                    "includesModelWeights": False,
                },
                indent=2,
            )
            + "\n"
        )
        for path in target.iterdir():
            if path.is_file():
                os.chmod(path, 0o600)
        (target / "SHA256SUMS").write_text(
            "".join(
                f"{file_sha256(p)}  {p.name}\n" for p in sorted(target.iterdir()) if p.is_file()
            )
        )
        os.chmod(target / "SHA256SUMS", 0o600)
    finally:
        # Failed partial backups also remain private.
        for path in target.iterdir():
            if path.is_file():
                os.chmod(path, 0o600)
        if writers and not getattr(args, "keep_stopped", False):
            compose(args.env_file, "start", *reversed(writers))
    print(f"Consistent target stack backup created: {target}")


def validate_ai_archive(archive):
    roots = set()
    with tarfile.open(archive) as source:
        for item in source.getmembers():
            parts = Path(item.name).parts
            if item.name.startswith("/") or ".." in parts or not (item.isfile() or item.isdir()):
                raise ValueError("unsafe AI archive entry")
            if not parts:
                if not item.isdir():
                    raise ValueError("AI archive root must be a directory")
                continue
            if parts[0] not in ("documents", "chroma"):
                raise ValueError("AI archive may contain only documents and chroma volumes")
            if len(parts) == 1:
                if not item.isdir():
                    raise ValueError("AI archive volume roots must be directories")
                roots.add(parts[0])
    if roots != {"documents", "chroma"}:
        raise ValueError("AI archive must contain both documents and chroma directories")


def restore_stack(args):
    backup = args.backup.resolve()
    if not (backup / "SHA256SUMS").is_file():
        raise ValueError("full stack recovery requires a checksummed local-stack backup")
    required = {
        "metor_service.sql",
        "metor_ai.sql",
        "metor-data.tar.gz",
        "ai-data.tar.gz",
        "deployment.env",
        "embedding-models.json",
        "backup-manifest.json",
    }
    covered = set()
    for line in (backup / "SHA256SUMS").read_text().splitlines():
        digest, name = line.split("  ", 1)
        if (
            Path(name).name != name
            or (backup / name).is_symlink()
            or name in covered
            or not re.fullmatch(r"[0-9a-f]{64}", digest)
            or file_sha256(backup / name) != digest
        ):
            raise ValueError("backup checksum validation failed")
        covered.add(name)
    if not required.issubset(covered):
        raise ValueError("backup checksum list does not cover all required recovery files")
    manifest = json.loads((backup / "backup-manifest.json").read_text())
    if (
        manifest.get("formatVersion") != 1
        or manifest.get("project") not in ALLOWED_PROJECTS
        or set(manifest.get("databases", [])) != {"metor_service", "metor_ai"}
    ):
        raise ValueError("unsupported full-stack backup manifest")
    sql = (backup / "metor_ai.sql").read_bytes()
    validate_sql(sql, "metor_ai")
    validate_sql((backup / "metor_service.sql").read_bytes(), "metor_service")
    if (
        mysql(
            args.env_file,
            (
                b"SELECT COUNT(*) FROM information_schema.tables "
                b"WHERE table_schema IN ('metor_service','metor_ai');\n"
            ),
        ).strip()
        != b"0"
    ):
        raise ValueError("full stack recovery requires new empty business databases/volumes")
    archive = backup / "ai-data.tar.gz"
    validate_ai_archive(archive)
    files = compose(
        args.env_file,
        "run",
        "--rm",
        "-T",
        "--no-deps",
        "--entrypoint",
        "sh",
        "ai-runtime",
        "-c",
        "find /data/ai -type f -print -quit",
        capture_output=True,
    ).stdout.strip()
    if files:
        raise ValueError("restore refuses an existing AI file volume")
    restore_metor(args)
    mysql(args.env_file, sql, "metor_ai")
    with subprocess.Popen(["gzip", "-dc", str(archive)], stdout=subprocess.PIPE) as unpack:
        compose(
            args.env_file,
            "run",
            "--rm",
            "-T",
            "--no-deps",
            "--entrypoint",
            "tar",
            "ai-runtime",
            "--no-same-owner",
            "--no-same-permissions",
            "--no-overwrite-dir",
            "-C",
            "/data/ai",
            "-xf",
            "-",
            "./documents",
            "./chroma",
            stdin=unpack.stdout,
        )
        if unpack.wait() != 0:
            raise ValueError("AI archive decompression failed")
    print(
        "New full-stack backup restored; validate model identity, migrations "
        "and retrieval before serving requests."
    )


def build(args):
    if WORKSPACE is None:
        raise ValueError(
            "source build requires the three-repository workspace, not an exported bundle"
        )
    config = read_env(args.env_file)
    services = args.service or ["ai", "metor", "frontend"]
    if args.offline and services != ["ai"]:
        raise ValueError(
            "offline source build is only supported for --service ai; deploy "
            "exported full-stack images with docker load"
        )
    components = {
        "ai": ("ai-runtime-service", "AI_RUNTIME_IMAGE"),
        "metor": ("metor-service", "METOR_IMAGE"),
        "frontend": ("frontend", "FRONTEND_IMAGE"),
    }
    for service in services:
        directory, key = components[service]
        options = ["docker", "build", "--platform", config["METOR_PLATFORM"], "-t", config[key]]
        if args.offline:
            options += ["--network=none"]
            if key == "AI_RUNTIME_IMAGE":
                options += ["--build-arg", "AI_OFFLINE_BUILD=1"]
            if key == "METOR_IMAGE":
                options += ["--build-arg", "GRADLE_OFFLINE=1"]
        run([*options, str(WORKSPACE / directory)])


def export_bundle(args):
    target = args.output.resolve()
    target.mkdir(parents=True, exist_ok=False)
    config = read_env(args.env_file)
    images = [
        config[key] for key in ("MYSQL_IMAGE", "AI_RUNTIME_IMAGE", "METOR_IMAGE", "FRONTEND_IMAGE")
    ]
    image_records = json.loads(
        run(["docker", "image", "inspect", *images], capture_output=True, text=True).stdout
    )
    if WORKSPACE is None:
        raise ValueError("export requires the original source workspace")
    # Include only portable deployment inputs, never private envs, backups or host data.
    package_deployment = target / "deployment"
    package_deployment.mkdir()
    for name in [*FILES, "compose.shared-runtime.yaml", "compose.license-host.yaml",
                 ".env.full-local.example", "README.md"]:
        shutil.copy2(DEPLOYMENT / name, package_deployment / name)
    shutil.copytree(DEPLOYMENT / "mysql-init", package_deployment / "mysql-init")
    shutil.copytree(DEPLOYMENT / "migrations", package_deployment / "migrations")
    (package_deployment / "scripts").mkdir()
    shutil.copy2(Path(__file__), package_deployment / "scripts/local-stack.py")
    shutil.copy2(DEPLOYMENT / "scripts/license_init.py",
                 package_deployment / "scripts/license_init.py")
    for name in ("import-images.sh", "verify-bundle.sh", "install-model.sh", "rebuild-chroma.sh"):
        shutil.copy2(DEPLOYMENT / "scripts" / name, package_deployment / "scripts" / name)
    catalog_path = package_deployment / "config/embedding-models.example.json"
    catalog_path.parent.mkdir(parents=True)
    shutil.copy2(DEFAULT_CATALOG, catalog_path)
    (target / "images").mkdir()
    run(["docker", "save", "--output", str(target / "images/full-stack.tar"), *images])
    shutil.copytree(DEPLOYMENT / "docs", package_deployment / "docs")
    repos = {}
    for name in ("frontend", "ai-runtime-service", "metor-service"):
        repos[name] = {
            "head": run(
                ["git", "-C", str(WORKSPACE / name), "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
            ).stdout.strip(),
            "workingTree": run(
                ["git", "-C", str(WORKSPACE / name), "status", "--porcelain"],
                capture_output=True,
                text=True,
            ).stdout.splitlines(),
        }
    manifest = {
        "formatVersion": 1,
        "project": PROJECT,
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "images": [
            {
                "reference": ref,
                "id": record["Id"],
                "architecture": record["Architecture"],
                "os": record["Os"],
            }
            for ref, record in zip(images, image_records)
        ],
        "repos": repos,
        "includesCredentials": False,
        "includesBusinessData": False,
        "includesModelWeights": False,
    }
    (target / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    (target / "SHA256SUMS").write_text(
        "".join(
            f"{file_sha256(p)}  {p.relative_to(target)}\n"
            for p in sorted(target.rglob("*"))
            if p.is_file()
        )
    )
    print(f"Portable full-stack deployment bundle created: {target}")


def mysql_cli(args):
    account = {
        "root": ("root", "MYSQL_ROOT_PASSWORD", ""),
        "ai": ("ai_user", "MYSQL_PASSWORD", "metor_ai"),
        "metor": ("metor_user", "METOR_DB_PASSWORD", "metor_service"),
    }[args.account]
    user, key, database = account
    command = f'MYSQL_PWD="${key}" exec mysql -A -u{user}'
    if database:
        command += " " + database
    compose(args.env_file, "exec", "mysql", "sh", "-c", command)


def ensure_native_services_stopped():
    import socket

    for port in (8080, 8090):
        with socket.socket() as probe:
            probe.settimeout(1)
            if probe.connect_ex(("127.0.0.1", port)) == 0:
                raise ValueError(f"stop the native service on {port} before Docker mode or backup")


def switch_mode(args):
    if args.mode == "local":
        compose(args.env_file, "stop", "frontend", "metor", "ai-runtime")
        compose(args.env_file, "up", "-d", "--wait", "mysql")
        print("Local mode ready: start AI, Metor and Vite from their source repositories.")
    else:
        ensure_native_services_stopped()
        compose(args.env_file, "up", "-d", "--wait")
        print("Docker mode ready: http://127.0.0.1:18180/")


def main():
    global PROJECT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", choices=ALLOWED_PROJECTS, default=PROJECT)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV)
    commands = parser.add_subparsers(dest="command", required=True)
    license_create = commands.add_parser("license-init",
        help="Initialize offline licensing identity and clocks without changing database credentials")
    license_create.add_argument("--license-root", type=Path, default=RUNTIME_ROOT / "license")
    create = commands.add_parser("init")
    create.add_argument("--model-path", type=Path, required=True)
    create.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    create.add_argument("--metor-env-file", type=Path)
    restore = commands.add_parser("restore-metor")
    restore.add_argument("backup", type=Path)
    recover = commands.add_parser("restore-stack")
    recover.add_argument("backup", type=Path)
    backup = commands.add_parser("backup")
    backup.add_argument("backup", type=Path)
    backup.add_argument(
        "--keep-stopped",
        action="store_true",
        help=(
            "leave originally running writers stopped for an update; also applies on backup failure"
        ),
    )
    image_build = commands.add_parser("build")
    image_build.add_argument(
        "--offline", action="store_true", help="only supported with --service ai"
    )
    image_build.add_argument("--service", choices=("ai", "metor", "frontend"), action="append")
    export = commands.add_parser("export")
    export.add_argument("output", type=Path)
    sql_cli = commands.add_parser("mysql")
    sql_cli.add_argument("account", nargs="?", choices=("root", "ai", "metor"), default="root")
    mode = commands.add_parser("mode")
    mode.add_argument("mode", choices=("local", "docker"))
    compose_command = commands.add_parser("compose")
    compose_command.add_argument("args", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    args.env_file = args.env_file.resolve()
    PROJECT = args.project
    try:
        if args.command == "compose":
            forwarded = args.args[1:] if args.args[:1] == ["--"] else args.args
            if not forwarded:
                forwarded = ["ps"]
            if forwarded[:1] == ["config"] and "--quiet" not in forwarded and "-q" not in forwarded:
                raise ValueError("use compose config --quiet; expanded config exposes credentials")
            forbidden = (
                "-p",
                "--project-name",
                "--env-file",
                "-f",
                "--file",
                "--project-directory",
            )
            if any(arg.split("=", 1)[0] in forbidden for arg in forwarded):
                raise ValueError(
                    "project and configuration overrides must use the validated wrapper options"
                )
            if "-v" in forwarded or "--volumes" in forwarded:
                raise ValueError(
                    "this wrapper preserves data volumes; destructive volume removal is "
                    "not supported"
                )
            compose(args.env_file, *forwarded)
        else:
            {
                "mysql": mysql_cli,
                "mode": switch_mode,
                "init": init,
                "license-init": license_init,
                "restore-metor": restore_metor,
                "backup": backup_stack,
                "restore-stack": restore_stack,
                "build": build,
                "export": export_bundle,
            }[args.command](args)
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print(f"Local stack operation failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
