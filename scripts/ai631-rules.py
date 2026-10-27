#!/usr/bin/env python3
"""Read six legacy rule tables and generate offline upserts. Python 3.8, stdlib only."""

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# Target contract: Metor Flyway V3. '?' means nullable; t is a MySQL TEXT.
RULES = {
    "ace_bit_event_dictionary": ("diag_bit_event_dict",
        "id:i64 module_type:s50 event_name:s50 args1:i16 args1_desc:s256 "
        "args2:i64 args2_desc:s256 args3:i64 args3_desc:s256 is_fault:b label:s64 "
        "description:t? failure_mode:t? effect:t? external_advice:t? internal_advice:t?"),
    "ace_fault_event_dictionary": ("diag_fault_event_dict",
        "id:i64 module_type:s50 event_name:s100 args1_desc:t? args2_desc:t? args3_desc:t? "
        "node_name:s50 event_function:t is_fault:b common_params:t? fault_reason:t? "
        "fault_impact:t? remark:t?"),
    "ace_sys_call_dictionary": ("diag_syscall_dict",
        "id:i64 module_type:s50 args2:i32 args2_desc:s200? function_definition:t? "
        "args3:i32 args3_desc:t? label:s50? driver:s100?"),
    "ace_running_state_dictionary": ("diag_running_state_dict",
        "id:i64 module_type:s50 event_name:s100 document_name:s100 chapter:s20 "
        "bit_position:s20 bit_description:s200 bit_value:s20 bit_value_description:s200 mask:s20"),
    "ace_running_state_rule": ("diag_running_state_rule",
        "id:i64 event_name:s100 args1:i32 args1_desc:s256 args2:i32 args2_desc:s256 "
        "args3:i32 args3_desc:s256 is_fault:b label:s64 description:t? driver_type:s50 "
        "manual_name:s100 chapter:s50 register_name:s100"),
    "ace_special_dictionary": ("diag_special_dict",
        "id:i64 event_name:s100 args1:i16? args1_desc:t? args2:i64? args2_desc:t? "
        "args3:i64? args3_desc:t? is_fault:b tag:s50? description:t? driver:s100? fault_impact:t?"),
}


def columns(table):
    return [tuple(field.split(":")) for field in RULES[table][1].split()]


def numeric(kind):
    return kind.startswith("i") or kind == "b"


def validate(payload):
    if (not isinstance(payload, dict) or payload.get("formatVersion") != 1
            or not isinstance(payload.get("tables"), dict) or set(payload["tables"]) != set(RULES)):
        raise ValueError("snapshot must contain all six legacy tables, including empty ones")
    for source, (target, _) in RULES.items():
        table = payload["tables"][source]
        fields = columns(source)
        if (not isinstance(table, dict) or table.get("targetTable") != target
                or table.get("columns") != [name for name, _ in fields]
                or not isinstance(table.get("rows"), list)):
            raise ValueError("snapshot schema differs from reviewed mapping: " + source)
        seen = set()
        for row in table["rows"]:
            if not isinstance(row, list) or len(row) != len(fields):
                raise ValueError("invalid snapshot row width: " + source)
            for value, (name, spec) in zip(row, fields):
                kind = spec.rstrip("?")
                if value is None and spec.endswith("?"):
                    continue
                if numeric(kind):
                    low, high = (0, 1) if kind == "b" else (
                        -(2 ** (int(kind[1:]) - 1)), 2 ** (int(kind[1:]) - 1) - 1)
                    valid = type(value) is int and low <= value <= high
                else:
                    valid = isinstance(value, str)
                    if valid:
                        valid = (len(value.encode("utf-8")) <= 65535 if kind == "t"
                                 else len(value) <= int(kind[1:]))
                if not valid:
                    raise ValueError("invalid/null/oversized value: " + source + "." + name)
            if row[0] <= 0 or row[0] in seen:
                raise ValueError("primary keys must be positive and unique: " + source)
            seen.add(row[0])


def private_files(contents):
    """Create new private files only; never replace a previous customer export."""
    created = []
    try:
        for path, raw in contents:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            created.append(path)
            with os.fdopen(fd, "wb") as output:
                output.write(raw)
    except BaseException:
        for path in created:
            path.unlink()
        raise


def client(args, sql):
    result = subprocess.run([
        args.mysql_client, "--defaults-file=" + str(args.defaults_file.absolute()),
        "--default-character-set=utf8mb4", "--batch", "--raw", "--skip-column-names",
        "--database=" + args.database,
    ], input=sql, capture_output=True, text=True, encoding="utf-8")
    if result.returncode:
        raise ValueError("source MySQL query failed; check client/config/permissions/schema; no row data printed")
    return result.stdout


def export_snapshot(args):
    config = args.defaults_file
    info = config.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_nlink != 1:
        raise ValueError("MySQL defaults file must be an independent regular file with mode 0600")
    names = ",".join("'" + name + "'" for name in RULES)
    metadata = client(args,
        "SELECT 'T',TABLE_NAME,ENGINE FROM information_schema.TABLES "
        "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME IN (" + names + ");\n"
        "SELECT 'C',TABLE_NAME,COLUMN_NAME,DATA_TYPE FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME IN (" + names + ");\n")
    engines, types = {}, {name: {} for name in RULES}
    for line in metadata.splitlines():
        parts = line.split("\t")
        if len(parts) == 3 and parts[0] == "T" and parts[1] in RULES:
            engines[parts[1]] = parts[2]
        elif len(parts) == 4 and parts[0] == "C" and parts[1] in RULES:
            types[parts[1]][parts[2]] = parts[3]
        else:
            raise ValueError("unexpected source schema metadata")
    integer_types = {"bit", "tinyint", "smallint", "mediumint", "int", "bigint"}
    text_types = {"char", "varchar", "tinytext", "text", "mediumtext", "longtext"}
    for source in RULES:
        if engines.get(source, "").lower() != "innodb":
            raise ValueError("all six source tables must exist and use InnoDB: " + source)
        if set(types[source]) != {name for name, _ in columns(source)}:
            raise ValueError("source columns changed; review mapping before export: " + source)
        for name, spec in columns(source):
            allowed = integer_types if numeric(spec.rstrip("?")) else text_types
            if types[source][name] not in allowed:
                raise ValueError("source column type changed: " + source + "." + name)
    sql = ["SET SESSION TRANSACTION ISOLATION LEVEL REPEATABLE READ;",
           "START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY;"]
    for source in RULES:
        sql.append("SELECT 'TABLE','" + source + "';")
        expressions = []
        for name, spec in columns(source):
            field = "`" + name + "`"
            value = "CAST(" + field + " AS UNSIGNED)" if types[source][name] == "bit" else field
            # ASCII hex framing preserves tabs/newlines, NULL, empty strings and BIT booleans.
            expressions.append("IF(" + field + " IS NULL,'N',CONCAT('H',HEX(CONVERT("
                               + value + " USING utf8mb4))))")
        sql.append("SELECT 'ROW','" + source + "'," + ",".join(expressions)
                   + " FROM `" + source + "` ORDER BY `id`;")
    sql.append("COMMIT;")
    raw = client(args, "\n".join(sql))
    payload = {"formatVersion": 1, "createdAt": datetime.now(timezone.utc).isoformat(),
               "tables": {name: {"targetTable": target, "columns": [n for n, _ in columns(name)],
                                 "rows": []} for name, (target, _) in RULES.items()}}
    marked = set()
    current = None
    for line in raw.splitlines():
        parts = line.split("\t")
        if len(parts) == 2 and parts[0] == "TABLE" and parts[1] in RULES:
            current = parts[1]
            if current in marked:
                raise ValueError("duplicate table in snapshot stream")
            marked.add(current)
        elif (len(parts) >= 3 and parts[0] == "ROW" and parts[1] == current
              and len(parts) - 2 == len(columns(current))):
            row = []
            for token, (_, spec) in zip(parts[2:], columns(current)):
                if token == "N":
                    row.append(None)
                else:
                    if re.fullmatch(r"H(?:[0-9A-F]{2})*", token) is None:
                        raise ValueError("invalid source value framing")
                    value = bytes.fromhex(token[1:]).decode("utf-8")
                    if numeric(spec.rstrip("?")):
                        if re.fullmatch(r"-?(?:0|[1-9][0-9]*)", value) is None:
                            raise ValueError("invalid source integer")
                        value = int(value)
                    row.append(value)
            payload["tables"][current]["rows"].append(row)
        else:
            raise ValueError("unexpected source snapshot stream")
    if marked != set(RULES):
        raise ValueError("incomplete source snapshot")
    validate(payload)
    private_files([(args.output, json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8") + b"\n")])
    print("Read-only snapshot created; rows=" + json.dumps(
        {name: len(table["rows"]) for name, table in payload["tables"].items()}))


def literal(value):
    if value is None:
        return "NULL"
    if type(value) is int:
        return str(value)
    # Independent of NO_BACKSLASH_ESCAPES/ANSI_QUOTES and safe for literal SQL punctuation.
    return "CONVERT(X'" + value.encode("utf-8").hex() + "' USING utf8mb4)"


def batches(rows):
    batch, size = [], 0
    for row in rows:
        text = "(" + ",".join(literal(v) for v in row) + ")"
        if batch and (len(batch) >= 500 or size + len(text) > 1024 * 1024):
            yield batch
            batch, size = [], 0
        batch.append(text)
        size += len(text) + 2
    if batch:
        yield batch


def convert_snapshot(args):
    raw = args.input.read_bytes()
    payload = json.loads(raw)
    validate(payload)
    lines = ["-- AI631 customer rule snapshot; review report before explicit import.",
             "SET NAMES utf8mb4;", "SET @icp_rules_old_mode=@@SESSION.sql_mode;",
             "SET SESSION sql_mode=CONCAT_WS(',',@@SESSION.sql_mode,'STRICT_ALL_TABLES');",
             "START TRANSACTION;"]
    report = {"formatVersion": 1, "mode": "upsert-preserve-target-extras",
              "sourceSha256": hashlib.sha256(raw).hexdigest(), "tables": []}
    for source, (target, _) in RULES.items():
        table = payload["tables"][source]
        fields = table["columns"]
        for batch in batches(table["rows"]):
            lines.append("INSERT INTO `" + target + "` (" + ",".join("`" + n + "`" for n in fields) + ") VALUES")
            lines.append(",\n".join(batch))
            lines.append("ON DUPLICATE KEY UPDATE " + ",".join(
                "`" + n + "`=VALUES(`" + n + "`)" for n in fields if n != "id") + ";")
        report["tables"].append({"sourceTable": source, "targetTable": target, "rows": len(table["rows"])})
    lines.extend(["COMMIT;", "SET SESSION sql_mode=@icp_rules_old_mode;"])
    for record in report["tables"]:
        target = record["targetTable"]
        lines.append("SELECT '" + target + "' AS table_name," + str(record["rows"])
                     + " AS source_rows,COUNT(*) AS target_rows FROM `" + target + "`;")
    sql = ("\n".join(lines) + "\n").encode("utf-8")
    report["sqlSha256"] = hashlib.sha256(sql).hexdigest()
    report_path = args.output.with_suffix(".report.json")
    private_files([(args.output, sql),
                   (report_path, json.dumps(report, ensure_ascii=False, indent=2).encode("utf-8") + b"\n")])
    print("SQL and count/SHA256 report created; no target database connection or writes performed.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    export = actions.add_parser("export", help="read-only consistent snapshot from source MySQL")
    export.add_argument("--defaults-file", type=Path, required=True)
    export.add_argument("--database", required=True)
    export.add_argument("--mysql-client", default="mysql")
    export.add_argument("--output", type=Path, required=True)
    convert = actions.add_parser("convert", help="offline JSON snapshot to target upsert SQL + report")
    convert.add_argument("--input", type=Path, required=True)
    convert.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        (export_snapshot if args.action == "export" else convert_snapshot)(args)
    except (ValueError, OSError, UnicodeError) as error:
        # Never include row values, client stderr or credentials in the console.
        message = str(error) if isinstance(error, ValueError) and not isinstance(
            error, (json.JSONDecodeError, UnicodeError)) else "check input, client, paths and existing output files"
        print("Rules migration failed: " + message, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
