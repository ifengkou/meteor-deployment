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
        self.args = argparse.Namespace(
            env_file=self.env,
            model_path=self.root / "model",
            catalog=self.catalog,
            metor_env_file=None,
        )

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

    def test_export_packages_deployment_docs_and_catalog_without_private_config(self):
        with patch("builtins.print"):
            stack.init(self.args)
        config = stack.read_env(self.env)
        for key in ("MYSQL_IMAGE", "AI_RUNTIME_IMAGE", "METOR_IMAGE", "FRONTEND_IMAGE"):
            config[key] = key.lower() + ":fixture"
        target = self.root / "bundle"

        def fake_run(command, **kwargs):
            if command[:3] == ["docker", "image", "inspect"]:
                return SimpleNamespace(stdout=json.dumps([
                    {"Id": "fixture", "Architecture": "amd64", "Os": "linux"}
                    for _ in range(4)
                ]))
            if command[:2] == ["docker", "save"]:
                Path(command[3]).write_bytes(b"fixture archive")
                return SimpleNamespace(stdout="")
            return SimpleNamespace(stdout="fixture\n")

        with patch.object(stack, "read_env", return_value=config), \
                patch.object(stack, "run", side_effect=fake_run), patch("builtins.print"):
            stack.export_bundle(argparse.Namespace(env_file=self.env, output=target))
        self.assertTrue((target / "deployment/docs/amd64.md").is_file())
        self.assertTrue((target / "deployment/config/embedding-models.example.json").is_file())
        self.assertFalse((target / "runtime").exists())
        self.assertFalse((target / "deployment/.env.full-local").exists())
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
        with patch.object(stack, "compose") as compose:
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
        self.assertFalse(any(call.args[1] == "start" for call in compose.call_args_list))

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
            patch.object(stack, "compose", return_value=SimpleNamespace(stdout="")),
            patch("builtins.print"),
        ):
            stack.backup_stack(args)
        self.assertEqual(args.backup.stat().st_mode & 0o777, 0o700)
        for path in args.backup.iterdir():
            self.assertEqual(path.stat().st_mode & 0o777, 0o600, path.name)

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

    def test_compose_only_accepts_two_isolated_projects(self):
        with patch("builtins.print"):
            stack.init(self.args)
        with patch.object(stack, "PROJECT", "metor-service"), patch.object(stack, "run") as run:
            with self.assertRaisesRegex(ValueError, "unsupported"):
                stack.compose(self.env, "ps")
            run.assert_not_called()
        with (
            patch.object(stack, "PROJECT", "icp-diag-local-restore-check"),
            patch.object(stack, "run") as run,
        ):
            stack.compose(self.env, "ps")
            self.assertIn("icp-diag-local-restore-check", run.call_args.args[0])

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
