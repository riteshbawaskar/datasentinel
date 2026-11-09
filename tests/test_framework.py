"""Self-tests for DataSentinel's own building blocks (run with:  pytest -q).

These do not need Snowflake/Oracle/Databricks or a browser; they cover the logic that every
scenario relies on: encryption, config handling, comparison rules, validations, table parsing,
Excel cell comparison, unit discovery and report merging.
"""
import json

import pandas as pd
import pytest
import yaml
from cryptography.fernet import Fernet

from datasentinel.comparators.dataset_comparator import DatasetComparator
from datasentinel.comparators.excel_cell_comparator import ExcelCellComparator
from datasentinel.config_loader import ConfigError
from datasentinel.connectors import factory
from datasentinel.reporting.result_store import PASSED, ResultStore
from datasentinel.runner import discover_units
from datasentinel.security import crypto
from datasentinel.ui.table_parser import parse_html_table
from datasentinel.validators.data_validator import DataValidator


@pytest.fixture()
def key(monkeypatch):
    """A throw-away master key supplied through the environment."""
    k = Fernet.generate_key().decode()
    monkeypatch.setenv(crypto.ENV_KEY, k)
    return k


# ----------------------------------------------------------------------- encryption
def test_encrypt_roundtrip_and_randomised_tokens(key):
    t1, t2 = crypto.encrypt_value("s3cret"), crypto.encrypt_value("s3cret")
    assert t1 != t2 and t1.startswith("ENC(")          # random IV: same input, different token
    assert crypto.decrypt_value(t1) == "s3cret"
    assert crypto.decrypt_value("plain") == "plain"    # non-ENC values pass through


def test_wrong_key_is_rejected(key, monkeypatch):
    token = crypto.encrypt_value("x")
    monkeypatch.setenv(crypto.ENV_KEY, Fernet.generate_key().decode())
    with pytest.raises(crypto.SecurityError):
        crypto.decrypt_value(token)


def test_decrypt_tree_is_recursive_and_lazy(key):
    tree = {"a": {"password": crypto.encrypt_value("pw")}, "b": [crypto.encrypt_value("x"), 5]}
    assert crypto.decrypt_tree(tree) == {"a": {"password": "pw"}, "b": ["x", 5]}


def test_no_key_needed_without_encrypted_values(monkeypatch, tmp_path):
    monkeypatch.delenv(crypto.ENV_KEY, raising=False)
    monkeypatch.setenv(crypto.ENV_KEY_FILE, str(tmp_path / "missing.key"))
    assert crypto.decrypt_tree({"password": "plain"}) == {"password": "plain"}
    with pytest.raises(crypto.SecurityError):
        crypto.decrypt_tree({"password": "ENC(abc)"})   # key required only when needed


def test_encrypt_config_file_keeps_comments_and_skips_env(key, tmp_path):
    f = tmp_path / "c.yml"
    f.write_text("a:\n  password: tiger  # keep me\n  token: ${TOK}\n  user: scott\n")
    assert len(crypto.encrypt_config_file(f)) == 1
    text = f.read_text()
    assert "# keep me" in text and "${TOK}" in text and "tiger" not in text
    assert yaml.safe_load(text.split("#")[0] + "")  # still valid YAML
    assert crypto.decrypt_tree(yaml.safe_load(f.read_text()))["a"]["password"] == "tiger"


def test_factory_decrypts_only_when_building_connector(key, tmp_path):
    ep = {"type": "sqlite", "path": str(tmp_path / "x.db"), "password": crypto.encrypt_value("pw1")}
    assert ep["password"].startswith("ENC(")                     # config still encrypted
    assert factory.build_connector(ep).config["password"] == "pw1"   # decrypted in memory


# --------------------------------------------------------------------- comparison
def _cmp(src, tgt, **cfg):
    base = {"primary_key": ["ID"], "compare_fields": "all"}
    return DatasetComparator({**base, **cfg}).compare(pd.DataFrame(src), pd.DataFrame(tgt))


def test_compare_detects_missing_extra_and_mismatch():
    r = _cmp({"ID": [1, 2, 3], "V": ["a", "b", "c"]}, {"ID": [2, 3, 4], "V": ["b", "X", "d"]})
    assert list(r.missing_in_target["ID"]) == ["1"] and list(r.missing_in_source["ID"]) == ["4"]
    assert r.mismatched_rows == 1 and r.column_mismatch_counts == {"V": 1}


def test_compare_rules_tolerance_case_trim_null_and_key_types():
    r = _cmp({"ID": [1, 2, 3], "N": [1.0, 2.0, 3.0], "T": ["A", "B ", None]},
             {"ID": ["1", "2.0", 3], "N": [1.0004, 2.5, 3.0], "T": ["a", "B", ""]},
             options={"numeric_tolerance": 0.001, "ignore_case": True})
    assert r.matched_rows == 2 and r.mismatched_rows == 1      # only ID 2 (N: 2.0 vs 2.5)
    assert r.column_mismatch_counts == {"N": 1, "T": 0}


def test_compare_duplicates_mapping_and_exclude():
    r = _cmp({"ID": [1, 1, 2], "A": [1, 1, 2], "SKIP": [1, 2, 3]},
             {"CUST": [1, 2], "A": [1, 2], "SKIP": [9, 9]},
             column_mapping={"CUST": "ID"}, exclude_fields=["SKIP"])
    assert len(r.duplicates_source) == 1 and r.duplicates_source.iloc[0]["OCCURRENCES"] == 2
    assert r.compared_fields == ["A"] and r.mismatched_rows == 0


def test_compare_reports_config_errors():
    with pytest.raises(ConfigError):
        _cmp({"ID": [1]}, {"ID": [1]}, compare_fields=["NOPE"])
    with pytest.raises(ConfigError):
        DatasetComparator({"primary_key": ["ID"], "options": {"numeric_tolerence": 1}})


# --------------------------------------------------------------------- validation
def test_validator_checks_and_severity():
    df = pd.DataFrame({"ID": [1, 1, 3], "AMT": ["5", "x", "-1"], "EMAIL": ["a@b.co", None, "bad"]})
    cfg = {"checks": [
        {"type": "unique", "columns": ["ID"]},
        {"type": "numeric", "columns": ["AMT"]},
        {"type": "range", "column": "AMT", "min": 0},
        {"type": "not_null", "columns": ["EMAIL"]},
        {"type": "regex", "column": "EMAIL", "pattern": r"[^@]+@[^@]+\.\w+", "severity": "warning"},
        {"type": "nonsense"}, {"type": "not_null", "column": "MISSING"}]}
    out = {o.label: o for o in DataValidator(cfg).run(df)}
    assert not out["unique: ID"].passed and out["unique: ID"].failed_rows == 2
    assert out["numeric: AMT"].failed_rows == 1
    assert out["regex: EMAIL"].failed_rows == 1 and out["regex: EMAIL"].severity == "warning"
    assert any("Unknown check type" in o.message for o in out.values())
    assert any("column(s) not found" in o.message for o in out.values())   # reported, not raised


# ------------------------------------------------------------------ table parsing
def test_table_parser_handles_whitespace_ragged_rows_and_nesting():
    html = ("<table><tr><th>A</th><th>B</th></tr><tr><td> 1\n </td><td>x&nbsp;<b>y</b></td></tr>"
            "<tr><td>2</td><td><table><tr><td>inner</td></tr></table>z</td></tr><tr><td>3</td></tr></table>")
    assert parse_html_table(html).to_dict("records") == [
        {"A": "1", "B": "x y"}, {"A": "2", "B": "z"}, {"A": "3", "B": ""}]
    assert list(parse_html_table(html, header=False).columns) == ["COL_1", "COL_2"]


# --------------------------------------------------------------- excel cell compare
def _book(path, cells):
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "S"
    for ref, v in cells.items():
        ws[ref] = v
    wb.save(path)


def test_excel_cell_compare_locates_differences(tmp_path):
    _book(tmp_path / "a.xlsx", {"A1": "x", "B1": 1.0, "C1": "same", "D1": " t "})
    _book(tmp_path / "b.xlsx", {"A1": "y", "B1": 1.0004, "C1": "same", "D1": "T"})
    cfg = {"source": {"path": str(tmp_path / "a.xlsx")}, "target": {"path": str(tmp_path / "b.xlsx")},
           "options": {"numeric_tolerance": 0.001, "ignore_case": True}}
    r = ExcelCellComparator(cfg).compare()
    assert [d["cell"] for d in r.sheets[0].diffs] == ["A1"] and r.total_diffs == 1
    cfg["options"]["ignore_ranges"] = ["A1"]
    assert ExcelCellComparator(cfg).compare().passed


# --------------------------------------------------------- discovery + report merge
def test_discover_units_respects_tags_and_scheme():
    feats = discover_units(["features"], "feature", [])
    scen = discover_units(["features"], "scenario", [])
    assert 0 < len(feats) <= len(scen)
    # --tags on the command line REPLACES default_tags, so @demo_fail scenarios (excluded by
    # default) become selectable.
    fail = discover_units(["features"], "scenario", ["--tags=demo_fail"])
    assert fail and not {u.id for u in fail} & {u.id for u in scen}


def test_result_store_json_roundtrip_and_merge(tmp_path):
    paths = []
    for i in range(2):
        s = ResultStore("t")
        s.start_scenario("F", f"sc{i}", ["demo"])
        s.checkpoint("c", PASSED, 1, 1)
        s.attach_image("shot", b"\x89PNG")
        s.end_scenario("passed")
        p = tmp_path / f"{i}.json"
        s.write_json(p)
        paths.append(p)
    merged = ResultStore.merge(paths, "Merged", run_info={"workers": "2"})
    assert [x.name for x in merged.scenarios] == ["sc0", "sc1"]
    assert merged.totals()["checkpoints_passed"] == 2 and merged.scenarios[0].images[0].title == "shot"
    assert json.loads((paths[0]).read_text())["framework"] == "DataSentinel"
