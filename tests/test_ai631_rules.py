"""Customer re-export contracts: consistent reads, lossless values and offline SQL."""

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/ai631-rules.py"
spec = importlib.util.spec_from_file_location("ai631_rules", SCRIPT)
rules = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rules)


def fixture():
    tables = {}
    for source, (target, _) in rules.RULES.items():
        fields = rules.columns(source)
        row = [None if kind.endswith("?") else 1 if rules.numeric(kind)
               else "中文 $ ' \\ , ;\n\t\x00测试" if kind == "t" else "测试"
               for _, kind in fields]
        tables[source] = {"targetTable": target, "columns": [n for n, _ in fields], "rows": [row]}
    return {"formatVersion": 1, "tables": tables}


def stream(payload):
    lines = []
    for source, table in payload["tables"].items():
        lines.append("TABLE\t" + source)
        for row in table["rows"]:
            lines.append("ROW\t" + source + "\t" + "\t".join(
                "N" if v is None else "H" + str(v).encode("utf-8").hex().upper() for v in row))
    return "\n".join(lines) + "\n"


def metadata():
    lines = []
    for source in rules.RULES:
        lines.append("T\t" + source + "\tInnoDB")
        for name, kind in rules.columns(source):
            data_type = "bit" if kind == "b" else "bigint" if rules.numeric(kind.rstrip("?")) else "varchar"
            lines.append("C\t" + source + "\t" + name + "\t" + data_type)
    return "\n".join(lines) + "\n"


def test_export_consistent_snapshot_and_bit_cast_without_password_arguments(tmp_path):
    config = tmp_path / "source.cnf"
    config.write_text("[client]\npassword=synthetic-secret\n")
    config.chmod(0o600)
    args = SimpleNamespace(defaults_file=config, database="legacy", mysql_client="mysql", output=tmp_path / "source.json")
    payload = fixture()
    payload["tables"]["ace_sys_call_dictionary"]["rows"][0][2] = -2147483648
    with patch.object(rules.subprocess, "run", side_effect=[
        SimpleNamespace(returncode=0, stdout=metadata()),
        SimpleNamespace(returncode=0, stdout=stream(payload)),
    ]) as run:
        rules.export_snapshot(args)
    assert json.loads(args.output.read_text())["tables"] == payload["tables"]
    assert args.output.stat().st_mode & 0o777 == 0o600
    query = run.call_args.kwargs["input"]
    assert "WITH CONSISTENT SNAPSHOT, READ ONLY" in query
    assert "CAST(`is_fault` AS UNSIGNED)" in query
    assert "CAST(`id` AS SIGNED)" not in query
    assert "synthetic-secret" not in str(run.call_args_list)
    assert run.call_args.args[0][1] == "--defaults-file=" + str(config.absolute())
    for verb in ("INSERT ", "UPDATE ", "DELETE ", "LOCK TABLE", "DROP "):
        assert verb not in query


def test_export_rejects_missing_tables_changed_schema_and_nontransactional_source(tmp_path):
    config = tmp_path / "source.cnf"
    config.write_text("[client]\n")
    config.chmod(0o600)
    args = SimpleNamespace(defaults_file=config, database="legacy", mysql_client="mysql", output=tmp_path / "out.json")
    for text in (metadata().replace("InnoDB", "MyISAM", 1),
                 metadata().replace("\tid\t", "\tnew_column\t", 1), ""):
        with patch.object(rules, "client", return_value=text) as client:
            with pytest.raises(ValueError):
                rules.export_snapshot(args)
            assert client.call_count == 1
        assert not args.output.exists()


def test_convert_empty_table_special_characters_report_and_no_network(tmp_path):
    payload = fixture()
    payload["tables"]["ace_running_state_dictionary"]["rows"] = []
    source, output = tmp_path / "source.json", tmp_path / "target.sql"
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    source.write_bytes(raw)
    with patch.object(rules.subprocess, "run") as run:
        rules.convert_snapshot(SimpleNamespace(input=source, output=output))
        run.assert_not_called()
    sql = output.read_text()
    assert "START TRANSACTION" in sql and "COMMIT" in sql
    assert "ON DUPLICATE KEY UPDATE" in sql
    assert "INSERT INTO `diag_running_state_dict`" not in sql
    assert "0 AS source_rows" in sql
    assert "DELETE FROM" not in sql and "DROP TABLE" not in sql
    assert "CONVERT(X'" in sql
    assert "中文" not in sql
    report_path = output.with_suffix(".report.json")
    report = json.loads(report_path.read_text())
    assert report["sourceSha256"] == rules.hashlib.sha256(raw).hexdigest()
    assert report["sqlSha256"] == rules.hashlib.sha256(output.read_bytes()).hexdigest()
    assert len(report["tables"]) == 6
    assert output.stat().st_mode & 0o777 == report_path.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        rules.convert_snapshot(SimpleNamespace(input=source, output=output))
    assert output.read_text() == sql


@pytest.mark.parametrize("damage", ["duplicate", "missing", "width", "overflow", "null", "text"])
def test_invalid_snapshot_never_creates_sql(tmp_path, damage):
    payload = fixture()
    source_name = "ace_bit_event_dictionary"
    rows = payload["tables"][source_name]["rows"]
    if damage == "duplicate":
        rows.append(rows[0][:])
    elif damage == "missing":
        del payload["tables"][source_name]
    elif damage == "width":
        rows[0].pop()
    elif damage == "overflow":
        rows[0][3] = 32768
    elif damage == "null":
        rows[0][0] = None
    elif damage == "text":
        rows[0][1] = "超" * 51
    source, output = tmp_path / "source.json", tmp_path / "target.sql"
    source.write_text(json.dumps(payload))
    with pytest.raises(ValueError):
        rules.convert_snapshot(SimpleNamespace(input=source, output=output))
    assert not output.exists()


def test_partial_file_pair_failure_preserves_existing_report(tmp_path):
    payload = tmp_path / "source.json"
    payload.write_text(json.dumps(fixture()))
    output = tmp_path / "rules.sql"
    report = tmp_path / "rules.report.json"
    report.write_text("previous customer report")
    with pytest.raises(FileExistsError):
        rules.convert_snapshot(SimpleNamespace(input=payload, output=output))
    assert not output.exists()
    assert report.read_text() == "previous customer report"


def test_sql_batches_are_bounded_for_large_customer_tables_and_text():
    assert [len(batch) for batch in rules.batches([[i] for i in range(1001)])] == [500, 500, 1]
    batches = list(rules.batches([[i, "文" * 20000] for i in range(30)]))
    assert len(batches) > 1
    assert all(sum(len(row) + 2 for row in batch) <= 1024 * 1024 for batch in batches)
