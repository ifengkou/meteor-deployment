"""Safety contracts for deployment configuration and data recovery (no Docker needed)."""

import argparse
import importlib.util
import io
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

spec = importlib.util.spec_from_file_location(
    "local_stack", Path(__file__).resolve().parents[1] / "scripts/local-stack.py"
)
stack = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stack)


class LocalStackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "model").mkdir()
        (self.root / "model/config.json").write_text("{}")
        self.catalog = self.root / "catalog.json"
        self.catalog.write_text(
            json.dumps(
                {"models": [{"id": "bge", "modelPath": "/models/embedding", "enabled": True}]}
            )
        )
        self.env = self.root / "private/deployment.env"
        self.tools_patch = patch.object(stack.license_container, "LicenseTools")
        self.tools = self.tools_patch.start().return_value
        self.tools.image = "fixture"
        self.tools.probe = {"product_config_sha256": "a" * 64}
        self.artifacts_patch = patch("license_artifacts.inspect_images", return_value={"productConfigSha256": "a" * 64})
        self.artifacts_patch.start()
        self.addCleanup(self.artifacts_patch.stop)
        self.addCleanup(self.tools_patch.stop)
        self.args = argparse.Namespace(
            env_file=self.env,
            model_path=self.root / "model",
            catalog=self.catalog,
            metor_env_file=None,
        )

    def test_license_init_rejects_running_writers_before_image_probe_or_files(self):
        args = SimpleNamespace(env_file=self.env, license_root=self.root / "unused-license")
        with patch.object(stack, "read_env", return_value={}), \
             patch.object(stack, "ensure_native_services_stopped"), \
             patch.object(stack, "compose", return_value=SimpleNamespace(stdout="metor\n")):
            with self.assertRaisesRegex(ValueError, "stop metor"):
                stack.license_init(args)
        self.tools.initialize.assert_not_called()
        self.assertFalse(args.license_root.exists())

    def test_license_recovery_request_is_private_and_does_not_overwrite(self):
        output = self.root / "request.json"
        args = SimpleNamespace(env_file=self.env, recovery_action="request", output=output)
        raw = json.dumps({"kind": "clock-recovery-request", "recovery_code": "RC1A-example"}).encode()
        with patch.object(stack, "compose", return_value=SimpleNamespace(returncode=0, stdout=raw)) as call:
            stack.license_recovery(args)
            self.assertEqual(output.read_bytes(), raw)
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            command = call.call_args.args
            self.assertEqual(command[1:4], ("exec", "-T", "ai-runtime"))
            self.assertIn("app.operations.license_recovery", command)
            with self.assertRaises(FileExistsError):
                stack.license_recovery(args)
            self.assertEqual(output.read_bytes(), raw)

    def test_license_recovery_apply_streams_exact_file_only_to_ai(self):
        source = self.root / "recovery.json"
        source.write_bytes(b'{"signed":"example"}')
        args = SimpleNamespace(env_file=self.env, recovery_action="apply", file=source)
        with patch.object(stack, "compose", return_value=SimpleNamespace(returncode=0, stdout=b"{}")) as call:
            stack.license_recovery(args)
            self.assertEqual(call.call_args.kwargs["input"], source.read_bytes())
            self.assertEqual(call.call_args.args[-3:], ("apply", "--file", "-"))
            self.assertNotIn("metor", call.call_args.args)
        source.write_bytes(b"x" * 65537)
        with patch.object(stack, "compose") as call:
            with self.assertRaises(ValueError):
                stack.license_recovery(args)
            call.assert_not_called()

    def test_license_recovery_unknown_outcome_does_not_write_request(self):
        output = self.root / "request.json"
        args = SimpleNamespace(env_file=self.env, recovery_action="request", output=output)
        error = subprocess.CalledProcessError(2, ["recovery"], output=b'{"status":"OUTCOME_UNKNOWN"}')
        with patch.object(stack, "compose", side_effect=error):
            with self.assertRaisesRegex(ValueError, "same operation/file"):
                stack.license_recovery(args)
        self.assertFalse(output.exists())

    def test_layout_preserves_source_and_portable_config_roots(self):
        source = self.root / "workspace"
        for name in ("ai-runtime-service", "metor-service", "frontend"):
            (source / name).mkdir(parents=True)
            (source / name / "Dockerfile").touch()
        self.assertEqual(stack.deployment_layout(source / "deployment"),
                         (source / "ai-runtime-service", source))
        bundle = self.root / "bundle"
        self.assertEqual(stack.deployment_layout(bundle / "deployment"), (bundle, None))
        self.assertEqual(stack.DEFAULT_ENV, stack.RUNTIME_ROOT / "config/docker.env")
        self.assertEqual(stack.DEFAULT_CATALOG,
                         stack.DEPLOYMENT / "config/embedding-models.example.json")

    def test_default_catalog_maps_enabled_model_to_container_mount(self):
        self.args.catalog = stack.DEFAULT_CATALOG
        with patch("builtins.print"):
            stack.init(self.args)
        catalog = json.loads((self.env.parent / "embedding/docker.json").read_text())
        enabled = [m for m in catalog["models"] if m.get("enabled", True)]
        self.assertTrue(enabled)
        self.assertEqual({m["modelPath"] for m in enabled}, {"/models/embedding"})

    def test_portable_bundle_rejects_source_build_without_docker(self):
        with patch.object(stack, "WORKSPACE", None), patch.object(stack, "run") as run:
            with self.assertRaisesRegex(ValueError, "source build requires"):
                stack.build(argparse.Namespace(env_file=self.env, offline=False, service=None))
            run.assert_not_called()

    def test_export_packages_model_and_only_approved_credentials(self):
        with patch("builtins.print"):
            stack.init(self.args)
        config = stack.read_env(self.env)
        for key in ("MYSQL_IMAGE", "AI_RUNTIME_IMAGE", "METOR_IMAGE", "FRONTEND_IMAGE"):
            config[key] = key.lower() + ":fixture"
        target = self.root / "bundle"
        model = self.root / "model"
        for name in ("modules.json", "tokenizer_config.json", "tokenizer.json"):
            (model / name).write_text("{}")
        (model / "model.safetensors").write_bytes(b"synthetic weights")
        (model / "model-manifest.json").write_text(json.dumps({
            "artifactName": "bge-small-zh-v1.5", "dimension": 512,
        }))

        def fake_run(command, **kwargs):
            if command[:3] == ["docker", "image", "inspect"]:
                return SimpleNamespace(stdout=json.dumps([
                    {"Id": "fixture", "Architecture": "amd64", "Os": "linux"}
                    for _ in range(4)
                ]))
            if command[:2] == ["docker", "save"]:
                manifests = []
                with tarfile.open(command[3], "w") as archive:
                    for i, reference in enumerate(command[4:]):
                        raw = json.dumps({"os": "linux", "architecture": "amd64", "fixture": i}).encode()
                        name = f"config-{i}.json"
                        info = tarfile.TarInfo(name); info.size = len(raw)
                        archive.addfile(info, io.BytesIO(raw))
                        manifests.append({"Config": name, "RepoTags": [reference]})
                    raw = json.dumps(manifests).encode()
                    info = tarfile.TarInfo("manifest.json"); info.size = len(raw)
                    archive.addfile(info, io.BytesIO(raw))
                return SimpleNamespace(stdout="")
            if command[:2] == ["docker", "run"]:
                return SimpleNamespace(stdout='{"dimension":512}')
            return SimpleNamespace(stdout="fixture\n")

        compose_fixture = self.root / "compose-binary"
        compose_fixture.write_bytes(b"synthetic standalone Compose")
        package_compose = stack.customer_bundle.package_compose
        with patch.object(stack.customer_bundle, "COMPOSE_SHA256", stack.file_sha256(compose_fixture)), \
                patch.object(stack.customer_bundle, "package_compose",
                             side_effect=lambda source, destination: package_compose(compose_fixture, destination)), \
                patch.object(stack, "read_env", return_value=config), \
                patch.object(stack, "run", side_effect=fake_run), patch("builtins.print"):
            stack.export_bundle(argparse.Namespace(env_file=self.env, output=target,
                                                   credentials_env=self.env, model_path=model))
            compressed = self.root / "customer.tar.gz"
            stack.export_bundle(argparse.Namespace(env_file=self.env, output=compressed,
                                                   credentials_env=self.env, model_path=model))
        with tarfile.open(compressed) as archive:
            self.assertEqual(archive.extractfile("customer/models/embedding/model.safetensors").read(),
                             b"synthetic weights")
            self.assertIn(config["MYSQL_ROOT_PASSWORD"].encode(),
                          archive.extractfile("customer/deployment/config/customer.env").read())
            self.assertIn("customer/deployment/scripts/prepare-runtime.py", archive.getnames())
            self.assertIn("customer/deployment/scripts/ai631-rules.py", archive.getnames())
        self.assertEqual({p.name for p in (target / "deployment/docs").iterdir()},
                         set(stack.CUSTOMER_DOCUMENTS))
        self.assertFalse((target / "deployment/docs/customer-release/readiness.md").exists())
        self.assertFalse((target / "deployment/docs/arm64-local-validation-20261026.md").exists())
        self.assertFalse((target / "deployment/migrations/metor/README.md").exists())
        self.assertFalse((target / "deployment/.env.full-local.example").exists())
        import re
        for document in [target / "deployment/README.md", *(target / "deployment/docs").glob("*.md")]:
            for link in re.findall(r"\[[^\]]+\]\(([^)]+)\)", document.read_text()):
                if "://" not in link and not link.startswith("#"):
                    self.assertTrue((document.parent / link.split("#")[0]).exists(), str(document) + link)
        self.assertTrue((target / "deployment/config/embedding-models.example.json").is_file())
        self.assertFalse((target / "runtime").exists())
        self.assertFalse((target / "deployment/.env.full-local").exists())
        private = stack.customer_bundle.read_env(target / stack.customer_bundle.CREDENTIAL_PATH)
        self.assertEqual(set(private), set(stack.customer_bundle.CREDENTIAL_KEYS))
        self.assertEqual(private["MYSQL_ROOT_PASSWORD"], config["MYSQL_ROOT_PASSWORD"])
        self.assertTrue((target / "models/embedding/model.safetensors").is_file())
        manifest = json.loads((target / "manifest.json").read_text())
        self.assertEqual(set(manifest["repos"]),
                         {"frontend", "ai-runtime-service", "metor-service", "deployment"})
        self.assertEqual(manifest["repos"]["deployment"]["head"], "fixture")
        self.assertEqual(manifest["repos"]["deployment"]["workingTree"], ["fixture"])
        self.assertTrue(manifest["includesCredentials"])
        self.assertTrue(manifest["includesModelWeights"])
        self.assertEqual(manifest["compose"]["version"], "v2.33.0")
        self.assertEqual((target / manifest["compose"]["path"]).read_bytes(), compose_fixture.read_bytes())
        self.assertIn("deployment/bin/docker-compose-v2", (target / "SHA256SUMS").read_text())
        self.assertTrue((target / "deployment/bin/docker-compose-LICENSE").is_file())
        self.assertNotIn(config["MYSQL_ROOT_PASSWORD"], (target / "SHA256SUMS").read_text())
        portable_env = target / "runtime/config/docker.env"
        subprocess.run([
            sys.executable, str(target / "deployment/scripts/local-stack.py"),
            "--env-file", str(portable_env), "init",
            "--model-path", str(self.root / "model"),
        ], check=True, capture_output=True)
        self.assertTrue(portable_env.is_file())
        self.assertEqual(portable_env.stat().st_mode & 0o777, 0o600)

    def test_failed_update_backup_keeps_writers_stopped(self):
        with patch("builtins.print"):
            stack.init(self.args)
        args = argparse.Namespace(env_file=self.env, backup=self.root / "backup", keep_stopped=True)
        with patch.object(stack, "license_backup") as licensing, patch.object(stack, "compose") as compose:
            licensing.license_root.return_value = self.root / "license"
            compose.side_effect = [
                SimpleNamespace(stdout="frontend\nmetor\nai-runtime\n"),
                SimpleNamespace(),
                RuntimeError("dump failed"),
            ]
            with self.assertRaisesRegex(RuntimeError, "dump failed"):
                stack.backup_stack(args)
        self.assertEqual(
            compose.call_args_list[1].args[1:], ("stop", "frontend", "metor", "ai-runtime")
        )
        self.assertFalse(any(call.args[1] in ("start", "up") for call in compose.call_args_list))

    def test_shared_overlay_is_selected_without_changing_other_projects(self):
        with patch("builtins.print"):
            stack.init(self.args)
        with self.env.open("a") as output:
            output.write("WORKSPACE_RUNTIME_DIR=/test/runtime\n")
        with patch.object(stack, "run") as run:
            stack.compose(self.env, "config", "--quiet")
        self.assertIn(str(stack.DEPLOYMENT / "compose.shared-runtime.yaml"), run.call_args.args[0])

    def test_cli_keeps_password_out_of_command_arguments(self):
        with patch.object(stack, "compose") as compose:
            stack.mysql_cli(argparse.Namespace(env_file=self.env, account="ai"))
        self.assertEqual(
            compose.call_args.args[-1],
            'MYSQL_PWD="$MYSQL_PASSWORD" exec mysql -A -uai_user metor_ai',
        )

    def test_init_private_credentials_and_empty_ai_target(self):
        with patch("builtins.print"):
            stack.init(self.args)
        config = stack.read_env(self.env)
        self.assertEqual(config["METOR_DATABASE"], "metor_service")
        self.assertIn("@mysql:3306/metor_ai?", config["AI_DB_URL"])
        self.assertEqual(self.env.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.env.parent.stat().st_mode & 0o777, 0o700)
        self.assertEqual((self.env.parent / "embedding/docker.json").stat().st_mode & 0o777, 0o644)
        self.assertNotIn("phoenix", config.values())
        original = self.env.read_bytes()
        with self.assertRaises(ValueError):
            stack.init(self.args)
        self.assertEqual(self.env.read_bytes(), original)

    def test_existing_jwt_only_is_reused(self):
        source = self.root / "source.env"
        source.write_text(
            "METOR_PLATFORM_SECURITY_JWT_SECRET='a-test-secret-of-at-least-32-bytes'\nDB_PASSWORD=old-database-password\n"
        )
        self.args.metor_env_file = source
        with patch("builtins.print"):
            stack.init(self.args)
        config = stack.read_env(self.env)
        self.assertEqual(
            config["METOR_PLATFORM_SECURITY_JWT_SECRET"], "a-test-secret-of-at-least-32-bytes"
        )
        self.assertNotEqual(config["METOR_DB_PASSWORD"], "old-database-password")

    def test_refuses_sql_database_switch_before_connecting(self):
        backup = self.root / "backup"
        backup.mkdir()
        args = argparse.Namespace(env_file=self.env, backup=backup)
        for sql in (
            "USE phoenix;\n",
            "CREATE DATABASE phoenix;\n",
            "CREATE VIEW x AS SELECT * FROM `phoenix`.`y`;\n",
        ):
            (backup / "phoenix.sql").write_text(sql)
            with patch.object(stack, "mysql") as mysql:
                with self.assertRaises(ValueError):
                    stack.restore_metor(args)
                mysql.assert_not_called()

    def test_refuses_nonempty_business_database(self):
        backup = self.root / "backup"
        backup.mkdir()
        (backup / "phoenix.sql").write_text("CREATE TABLE example (id INT);\n")
        args = argparse.Namespace(env_file=self.env, backup=backup)
        with patch.object(stack, "mysql", return_value=b"28\n") as mysql:
            with self.assertRaisesRegex(ValueError, "nonempty"):
                stack.restore_metor(args)
            self.assertEqual(mysql.call_count, 1)

    def test_refuses_corrupted_backup_before_connecting(self):
        backup = self.root / "backup"
        backup.mkdir()
        (backup / "SHA256SUMS").write_text("0" * 64 + "  metor_service.sql\n")
        (backup / "metor_service.sql").write_text("altered")
        args = argparse.Namespace(env_file=self.env, backup=backup)
        with patch.object(stack, "mysql") as mysql:
            with self.assertRaisesRegex(ValueError, "checksum"):
                stack.restore_stack(args)
            mysql.assert_not_called()

    def test_restore_keeps_runtime_user_without_chown(self):
        backup = self.root / "backup"
        backup.mkdir()
        (backup / "phoenix.sql").write_text("CREATE TABLE example (id INT);\n")
        (backup / "metor-data").mkdir()
        self.env.parent.mkdir()
        args = argparse.Namespace(env_file=self.env, backup=backup)
        with (
            patch.object(stack, "mysql", return_value=b"0\n"),
            patch.object(stack, "compose", return_value=SimpleNamespace(stdout=b"")) as compose,
            patch.object(stack.subprocess, "Popen") as process,
            patch("builtins.print"),
        ):
            process.return_value.__enter__.return_value.stdout = io.BytesIO()
            process.return_value.__enter__.return_value.wait.return_value = 0
            stack.restore_metor(args)
        commands = [call.args[1:] for call in compose.call_args_list]
        self.assertTrue(commands)
        for command in commands:
            self.assertNotIn("--user", command)
            self.assertNotIn("chown", " ".join(command))
        extract = commands[-1][-1]
        self.assertIn("--no-same-owner", extract)
        self.assertIn("--no-same-permissions", extract)
        self.assertIn("--no-overwrite-dir", extract)

    def test_incomplete_checksum_list_rejected_before_connecting(self):
        backup = self.root / "backup"
        backup.mkdir()
        sql = backup / "metor_service.sql"
        sql.write_text("CREATE TABLE example (id INT);\n")
        (backup / "SHA256SUMS").write_text(stack.file_sha256(sql) + "  metor_service.sql\n")
        with patch.object(stack, "mysql") as mysql:
            with self.assertRaisesRegex(ValueError, "all required recovery files"):
                stack.restore_stack(argparse.Namespace(env_file=self.env, backup=backup))
            mysql.assert_not_called()

    def test_executable_sql_comment_and_cross_database_rejected(self):
        for sql in (
            b"/*!50000 USE phoenix */;",
            b"CREATE VIEW example AS SELECT * FROM metor_service.other;",
        ):
            with self.assertRaises(ValueError):
                stack.validate_sql(sql, "metor_ai")

    def test_offline_build_only_targets_ai(self):
        config = {"METOR_PLATFORM": "linux/arm64", "AI_RUNTIME_IMAGE": "ai:test"}
        with (
            patch.object(stack, "read_env", return_value=config),
            patch.object(stack, "run") as run,
        ):
            with self.assertRaisesRegex(ValueError, "only supported"):
                stack.build(argparse.Namespace(env_file=self.env, offline=True, service=None))
            run.assert_not_called()
            stack.build(argparse.Namespace(env_file=self.env, offline=True, service=["ai"]))
            self.assertEqual(run.call_count, 1)
            self.assertIn("--network=none", run.call_args.args[0])
            self.assertIn("AI_OFFLINE_BUILD=1", run.call_args.args[0])

    def test_backup_files_are_private(self):
        with patch("builtins.print"):
            stack.init(self.args)
        args = argparse.Namespace(env_file=self.env, backup=self.root / "backup")
        with (
            patch.object(stack.license_backup, "host_fingerprint", return_value=None),
            patch.object(stack.license_backup, "preflight"),
            patch.object(stack.license_backup, "backup", return_value={}),
            patch.object(stack, "compose", return_value=SimpleNamespace(stdout="")),
            patch("builtins.print"),
        ):
            stack.backup_stack(args)
        self.assertEqual(args.backup.stat().st_mode & 0o777, 0o700)
        for path in args.backup.iterdir():
            self.assertEqual(path.stat().st_mode & 0o777, 0o600, path.name)

    def test_backup_resumes_existing_writers_without_removed_migration_dependency(self):
        with patch("builtins.print"):
            stack.init(self.args)
        args = argparse.Namespace(env_file=self.env, backup=self.root / "backup")
        def compose_result(env, *command, **kwargs):
            if command[0] == "start":
                raise RuntimeError("ai-runtime is missing dependency ai-migrate")
            return SimpleNamespace(stdout="frontend\nmetor\nai-runtime\n" if command[0] == "ps" else "")
        with patch.object(stack.license_backup, "host_fingerprint", return_value=None), \
             patch.object(stack.license_backup, "preflight"), \
             patch.object(stack.license_backup, "backup", return_value={}), \
             patch.object(stack, "ensure_native_services_stopped"), \
             patch.object(stack, "compose", side_effect=compose_result) as compose, \
             patch("builtins.print"):
            stack.backup_stack(args)
        resumes = [call.args[1:] for call in compose.call_args_list if call.args[1] == "up"]
        self.assertEqual(resumes, [
            ("up", "-d", "--no-deps", "--no-recreate", "--wait", service)
            for service in ("ai-runtime", "metor", "frontend")
        ])

    def test_shared_backup_covers_native_configs_with_private_checksums(self):
        with patch("builtins.print"):
            stack.init(self.args)
        shared = self.root / "config"
        (shared / "embedding").mkdir(parents=True)
        for name in ("ai.local.env", "metor.local.env", "embedding/local.json"):
            (shared / name).write_text("test-private-configuration")
        with self.env.open("a") as output:
            output.write(f"WORKSPACE_RUNTIME_DIR={self.root}\n")
        args = argparse.Namespace(env_file=self.env, backup=self.root / "shared-backup")
        with (
            patch.object(stack.license_backup, "host_fingerprint", return_value=None),
            patch.object(stack.license_backup, "preflight"),
            patch.object(stack.license_backup, "backup", return_value={}),
            patch.object(stack, "compose", return_value=SimpleNamespace(stdout="")),
            patch.object(stack, "ensure_native_services_stopped"),
            patch("builtins.print"),
        ):
            stack.backup_stack(args)
        checksum_list = (args.backup / "SHA256SUMS").read_text()
        for name in ("ai.local.env", "metor.local.env", "embedding-local.json"):
            copied = args.backup / name
            self.assertEqual(copied.stat().st_mode & 0o777, 0o600)
            self.assertIn(f"{stack.file_sha256(copied)}  {name}", checksum_list)

    def test_compose_accepts_validated_isolated_project_names(self):
        with patch("builtins.print"):
            stack.init(self.args)
        with patch.object(stack, "PROJECT", "metor-service"), patch.object(stack, "run") as run:
            with self.assertRaisesRegex(ValueError, "unsupported"):
                stack.compose(self.env, "ps")
            run.assert_not_called()
        for project in ("icp-diag-local-restore-check", "icp-diag-arm64-verify"):
            with patch.object(stack, "PROJECT", project), patch.object(stack, "run") as run:
                stack.compose(self.env, "ps")
                self.assertIn(project, run.call_args.args[0])
        for project in ("icp-diag-../local", "icp-diag-UPPER", "icp-diag-a" + "b" * 64):
            with self.assertRaisesRegex(ValueError, "unsupported"):
                stack.project_name(project)

    def test_customer_compose_uses_only_verified_private_tool_and_preserves_source_cli(self):
        with patch("builtins.print"):
            stack.init(self.args)
        root = self.root.resolve() / "portable"
        deployment = root / "deployment"
        binary = root / stack.customer_bundle.COMPOSE_PATH
        binary.parent.mkdir(parents=True)
        binary.write_bytes(b"synthetic Compose executable")
        binary.chmod(0o755)
        checksum = stack.file_sha256(binary)
        record = {"version": "v2.33.0", "path": stack.customer_bundle.COMPOSE_PATH,
                  "sha256": checksum, "architecture": "amd64", "os": "linux"}
        (root / "manifest.json").write_text(json.dumps({"compose": record}))
        with patch.object(stack, "DEPLOYMENT", deployment), \
             patch.object(stack.customer_bundle, "COMPOSE_SHA256", checksum), \
             patch.object(stack, "run") as run:
            stack.compose(self.env, "ps")
            self.assertEqual(run.call_args.args[0][:2], ["docker", "compose"])
            with patch.object(stack, "WORKSPACE", None):
                stack.compose(self.env, "ps")
                self.assertEqual(run.call_args.args[0][0], str(binary))
                binary.unlink()
                run.reset_mock()
                with self.assertRaises((ValueError, FileNotFoundError)):
                    stack.compose(self.env, "ps")
                run.assert_not_called()

    def test_sql_import_uses_schema_account(self):
        with patch.object(stack, "compose", return_value=SimpleNamespace(stdout=b"")) as compose:
            stack.mysql(self.env, b"CREATE TABLE example (id INT);", "metor_service")
            command = compose.call_args.args
            self.assertIn("METOR_DB_PASSWORD", " ".join(map(str, command)))
            self.assertNotIn("-uroot", " ".join(map(str, command)))
            self.assertEqual(command[-1], "metor_service")
            with self.assertRaises(ValueError):
                stack.mysql(self.env, b"DROP TABLE example;", "phoenix")

    @unittest.skipUnless(
        sys.platform.startswith("linux"),
        "GNU tar integration requires Linux; macOS BSD tar does not support this flag",
    )
    def test_tar_preserves_existing_directory_metadata(self):
        # The runtime /data/ai parent is read-only while its child volumes are writable.
        # An archive may include '.', so extraction must leave existing directory
        # ownership, permissions and timestamps alone rather than suppressing errors.
        target = self.root / "extract"
        target.mkdir()
        archive = self.root / "data.tar"
        with tarfile.open(archive, "w") as output:
            directory = tarfile.TarInfo(".")
            directory.type = tarfile.DIRTYPE
            directory.mode = 0o700
            directory.mtime = 100
            output.addfile(directory)
        original_time = 1_000_000_000
        os.utime(target, (original_time, original_time))
        original_mode = target.stat().st_mode & 0o777
        subprocess.run(
            [
                "tar",
                "--no-same-owner",
                "--no-same-permissions",
                "--no-overwrite-dir",
                "-C",
                str(target),
                "-xf",
                str(archive),
            ],
            check=True,
        )
        self.assertEqual(target.stat().st_mode & 0o777, original_mode)
        self.assertEqual(target.stat().st_mtime, original_time)

    def test_ai_restore_preserves_readonly_parent_directory_metadata(self):
        backup = self.root / "backup"
        backup.mkdir()
        for name in ("metor_service.sql", "metor_ai.sql"):
            (backup / name).write_text("CREATE TABLE example (id INT);\n")
        for name in ("deployment.env", "embedding-models.json"):
            (backup / name).write_text("test")
        (backup / "backup-manifest.json").write_text(
            json.dumps(
                {
                    "formatVersion": 1,
                    "project": "icp-diag-local",
                    "databases": ["metor_service", "metor_ai"],
                }
            )
        )
        for name in ("ai-data.tar.gz", "metor-data.tar.gz"):
            with tarfile.open(backup / name, "w:gz") as archive:
                for member in (".", "./documents", "./chroma"):
                    directory = tarfile.TarInfo(member)
                    directory.type = tarfile.DIRTYPE
                    archive.addfile(directory)
        (backup / "SHA256SUMS").write_text(
            "".join(f"{stack.file_sha256(p)}  {p.name}\n" for p in backup.iterdir() if p.is_file())
        )
        args = argparse.Namespace(env_file=self.env, backup=backup)
        with (
            patch.object(stack.license_backup, "prepare_restore", return_value=None),
            patch.object(stack.license_backup, "host_fingerprint", return_value=None),
            patch.object(stack, "read_env", return_value={}),
            patch.object(stack, "mysql", return_value=b"0\n"),
            patch.object(stack, "compose", return_value=SimpleNamespace(stdout=b"")) as compose,
            patch.object(stack, "restore_metor"),
            patch.object(stack.subprocess, "Popen") as process,
            patch("builtins.print"),
        ):
            process.return_value.__enter__.return_value.stdout = io.BytesIO()
            process.return_value.__enter__.return_value.wait.return_value = 0
            stack.restore_stack(args)
        extract = compose.call_args.args[1:]
        self.assertIn("--no-overwrite-dir", extract)
        self.assertIn("--no-same-owner", extract)
        self.assertIn("--no-same-permissions", extract)
        self.assertNotIn("--user", extract)
        self.assertEqual(extract[-2:], ("./documents", "./chroma"))

    def test_ai_archive_refuses_extra_top_level_or_missing_volume(self):
        archive = self.root / "ai.tar.gz"
        for names in ((".", "./documents", "./chroma", "./other/secret"), (".", "./documents")):
            with tarfile.open(archive, "w:gz") as output:
                for name in names:
                    entry = tarfile.TarInfo(name)
                    entry.type = tarfile.DIRTYPE
                    output.addfile(entry)
            with self.assertRaises(ValueError):
                stack.validate_ai_archive(archive)

    @unittest.skipUnless(
        os.environ.get("P6_CONTAINER_RESTORE_TEST") == "1", "opt-in isolated Docker restore check"
    )
    def test_real_gnu_tar_with_readonly_parent_and_runtime_owned_child_mounts(self):
        image = os.environ.get("P6_AI_IMAGE", "ai-runtime-service:p6-local")
        base = [
            "docker",
            "run",
            "--rm",
            "--read-only",
            "--network",
            "none",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges:true",
        ]
        uid = subprocess.check_output([*base, "--entrypoint", "id", image, "-u"], text=True).strip()
        gid = subprocess.check_output([*base, "--entrypoint", "id", image, "-g"], text=True).strip()
        payload = io.BytesIO()
        with tarfile.open(fileobj=payload, mode="w") as output:
            for name in (".", "./documents", "./chroma"):
                entry = tarfile.TarInfo(name)
                entry.type = tarfile.DIRTYPE
                entry.mode = 0o755
                entry.mtime = 100
                output.addfile(entry)
            for name in ("./documents/probe.txt", "./chroma/probe.txt"):
                content = b"isolated-restore-proof\n"
                entry = tarfile.TarInfo(name)
                entry.size = len(content)
                entry.mode = 0o644
                output.addfile(entry, io.BytesIO(content))
        mounts = [
            "--tmpfs",
            f"/data/ai/documents:rw,mode=0755,uid={uid},gid={gid}",
            "--tmpfs",
            f"/data/ai/chroma:rw,mode=0755,uid={uid},gid={gid}",
        ]
        script = (
            "tar --no-same-owner --no-same-permissions --no-overwrite-dir "
            "-C /data/ai -xf - ./documents ./chroma && "
            'test "$(cat /data/ai/documents/probe.txt)" = isolated-restore-proof && '
            'test "$(cat /data/ai/chroma/probe.txt)" = isolated-restore-proof && test ! -w /data/ai'
        )
        subprocess.run(
            [*base, "-i", *mounts, "--entrypoint", "sh", image, "-c", script],
            input=payload.getvalue(),
            check=True,
        )


if __name__ == "__main__":
    unittest.main()
