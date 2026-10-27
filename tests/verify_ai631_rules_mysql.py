"""Opt-in real MySQL smoke, isolated container only; no ports or existing databases.

Run: python3 deployment/tests/verify_ai631_rules_mysql.py
Requires local mysql:8.4 Docker image. All credentials and rows are synthetic.
"""

import importlib.util
import json
import os
import secrets
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

DEPLOYMENT = Path(__file__).resolve().parents[1]
SCRIPT = DEPLOYMENT / "scripts/ai631-rules.py"
spec = importlib.util.spec_from_file_location("ai631_rules", SCRIPT)
rules = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rules)


def main():
    name = "icp-rule-migration-check-" + secrets.token_hex(4)
    password, reader_password = secrets.token_hex(24), secrets.token_hex(24)

    def docker(*args, **kwargs):
        return subprocess.run(["docker", *args], check=True, capture_output=True, text=True, **kwargs)

    def mysql(sql):
        return docker("exec", "-i", "--env", "MYSQL_PWD=" + password, name,
                      "mysql", "-uroot", "--default-character-set=utf8mb4", "--batch",
                      "--raw", "--skip-column-names", input=sql).stdout

    with tempfile.TemporaryDirectory(prefix="icp-rules-") as temporary:
        root = Path(temporary).resolve()
        config = root / "source.cnf"
        config.write_text("[client]\nuser=rules_reader\npassword=" + reader_password + "\n")
        config.chmod(0o600)
        docker("run", "-d", "--pull=never", "--name", name, "--network=none",
               "--mount", "type=bind,src=" + str(root) + ",dst=/fixtures,readonly",
               "--env", "MYSQL_ROOT_PASSWORD=" + password, "mysql:8.4")
        try:
            for _ in range(90):
                try:
                    mysql("SELECT 1;")
                    break
                except subprocess.CalledProcessError:
                    time.sleep(1)
            else:
                raise RuntimeError("disposable MySQL did not become ready")
            ddl = (DEPLOYMENT.parent / "metor-service/metor-app/src/main/resources/db/migration/"
                   "V3__report_files_and_dictionaries.sql").read_text()
            ddl = ddl[ddl.index("CREATE TABLE diag_bit_event_dict"):]
            mysql("CREATE DATABASE legacy_rules; CREATE DATABASE target_rules; USE target_rules;" + ddl)
            expected = {"formatVersion": 1, "tables": {}}
            for source, (target, _) in rules.RULES.items():
                fields = rules.columns(source)
                row = [None if kind.endswith("?") else 1 if rules.numeric(kind)
                       else "中文引号'\\;\n\t\x00😀" if kind == "t" else "测试"
                       for _, kind in fields]
                names = [n for n, _ in fields]
                if source == "ace_sys_call_dictionary":
                    row[names.index("args2")] = -2147483648
                    row[names.index("function_definition")] = "中文 ' \\ \n \t \x00 😀"
                if source == "ace_special_dictionary":
                    row[names.index("args2")] = 9223372036854775807
                    row[names.index("description")] = ""
                if source == "ace_fault_event_dictionary":
                    row[names.index("fault_reason")] = "café"
                mysql("CREATE TABLE legacy_rules.`" + source + "` LIKE target_rules.`" + target + "`;")
                if "is_fault" in names:
                    mysql("ALTER TABLE legacy_rules.`" + source + "` MODIFY is_fault BIT(1) NOT NULL;")
                if source == "ace_fault_event_dictionary":
                    mysql("ALTER TABLE legacy_rules.`" + source
                          + "` MODIFY fault_reason VARCHAR(1200) CHARACTER SET latin1 NULL;")
                mysql("INSERT INTO legacy_rules.`" + source + "` VALUES ("
                      + ",".join(rules.literal(v) for v in row) + ");")
                expected["tables"][source] = {"targetTable": target, "columns": names, "rows": [row]}
            mysql("CREATE USER 'rules_reader'@'localhost' IDENTIFIED BY '" + reader_password
                  + "'; GRANT SELECT ON legacy_rules.* TO 'rules_reader'@'localhost';")
            # Only the client runs in MySQL's container; the migration tool runs on the host.
            wrapper = root / "mysql-client"
            wrapper.write_text("#!/bin/sh\nshift\nexec docker exec -i " + name
                               + " mysql --defaults-file=/fixtures/source.cnf \"$@\"\n")
            wrapper.chmod(0o700)
            snapshot = root / "snapshot.json"
            rules.export_snapshot(SimpleNamespace(defaults_file=config, database="legacy_rules",
                                                   mysql_client=str(wrapper), output=snapshot))
            assert json.loads(snapshot.read_text())["tables"] == expected["tables"]
            output = root / "rules.sql"
            rules.convert_snapshot(SimpleNamespace(input=snapshot, output=output))
            # Exercise a mode where ordinary backslash-escaped SQL would corrupt text.
            mysql("USE target_rules; SET SESSION sql_mode='NO_BACKSLASH_ESCAPES,ANSI_QUOTES';"
                  + output.read_text())
            # Re-import also exercises the actual ON DUPLICATE KEY UPDATE path.
            mysql("USE target_rules;" + output.read_text())
            for source, table in expected["tables"].items():
                target = table["targetTable"]
                assert mysql("SELECT COUNT(*) FROM target_rules.`" + target + "`;").strip() == "1"
                for value, field in zip(table["rows"][0], table["columns"]):
                    literal = rules.literal(value)
                    assert mysql("SELECT COUNT(*) FROM target_rules.`" + target
                                 + "` WHERE `" + field + "` <=> " + literal + ";").strip() == "1"
            print("PASS: six nonempty tables, SELECT-only source account, real snapshot export, "
                  "BIT/latin1/UTF8/control characters/NULL/int boundaries, import twice, exact values/counts")
        finally:
            docker("rm", "-f", "-v", name)


if __name__ == "__main__":
    main()
