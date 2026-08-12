from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest
import rfc8785
from jsonschema import Draft202012Validator


STUDY_ROOT = Path(__file__).resolve().parents[1]
BUILDER_PATH = STUDY_ROOT / "scripts/build_dummy_analysis_fixture.py"
ANALYZER_PATH = STUDY_ROOT / "scripts/analyze_observation_ledger.py"
LEDGER_PATH = STUDY_ROOT / "dummy_analysis/DUMMY_OBSERVATION_LEDGER.json"
SUMMARY_PATH = STUDY_ROOT / "dummy_analysis/DUMMY_ANALYSIS_SUMMARY.json"
INPUT_SCHEMA_PATH = STUDY_ROOT / "schemas/observation-ledger.schema.json"
OUTPUT_SCHEMA_PATH = STUDY_ROOT / "schemas/analysis-summary.schema.json"


def _module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load(path: Path) -> dict:
    return json.loads(path.read_bytes())


def test_retained_dummy_ledger_and_analysis_replay_exactly() -> None:
    builder = _module(BUILDER_PATH, "dummy_builder")
    analyzer = _module(ANALYZER_PATH, "dummy_analyzer")
    assert rfc8785.dumps(builder.build()) == LEDGER_PATH.read_bytes()
    assert rfc8785.dumps(analyzer.analyze(LEDGER_PATH)) == SUMMARY_PATH.read_bytes()


def test_dummy_contracts_are_closed_and_retained_records_are_valid() -> None:
    input_schema = _load(INPUT_SCHEMA_PATH)
    output_schema = _load(OUTPUT_SCHEMA_PATH)
    Draft202012Validator.check_schema(input_schema)
    Draft202012Validator.check_schema(output_schema)
    assert list(Draft202012Validator(input_schema).iter_errors(_load(LEDGER_PATH))) == []
    assert list(Draft202012Validator(output_schema).iter_errors(_load(SUMMARY_PATH))) == []
    for schema in (input_schema, output_schema):
        stack = [schema]
        while stack:
            value = stack.pop()
            if isinstance(value, dict):
                if value.get("type") == "object":
                    assert value.get("additionalProperties") is False
                stack.extend(value.values())
            elif isinstance(value, list):
                stack.extend(value)


def test_planned_denominator_includes_every_failure_category() -> None:
    summary = _load(SUMMARY_PATH)
    assert summary["planned_row_count"] == 1480
    assert sum(summary["category_counts"].values()) == 1480
    assert summary["category_counts"]["GENERATION_FAILURE"] == 4
    assert summary["category_counts"]["MISSING_EXECUTION"] == 1
    assert summary["category_counts"]["ERROR"] == 1
    assert summary["terminal_only_denominator_used"] is False
    assert summary["conformance_mismatch_count"] == 8
    breakdown = summary["target_invalid_breakdown"]
    assert breakdown["planned_row_count"] == 1432
    assert breakdown["subtotals_reconcile"] is True
    assert breakdown["pooled_primary_result_permitted"] is False
    assert sum(
        item["planned_row_count"] for item in breakdown["by_profile_and_family"]
    ) == 1432
    assert all(
        len(item["accepted_unit_ids"]) == len(set(item["accepted_unit_ids"]))
        for item in breakdown["by_profile_and_family"]
    )


def test_dummy_data_never_authorizes_manuscript_wording() -> None:
    summary = _load(SUMMARY_PATH)
    assert summary["classification"] == "dummy_no_confirmatory_evidence"
    assert summary["manuscript_claims_authorized"] is False
    assert summary["all_required_propositions_evaluable_and_supported"] is False
    assert "analysis summaries cannot self-authorize manuscript claims" in summary[
        "authorization_blockers"
    ]
    assert summary["read_scope"] == {
        "dummy_input_only": True,
        "confirmatory_artifacts_read": False,
        "model_outputs_read": False,
        "network_used": False,
        "independent_review_performed": False,
    }
    assert all(not item["abstract_eligible"] for item in summary["propositions"])
    assert all(not item["conclusion_eligible"] for item in summary["propositions"])


def test_missing_planned_row_is_rejected_not_dropped_from_denominator(tmp_path: Path) -> None:
    analyzer = _module(ANALYZER_PATH, "dummy_analyzer_missing")
    ledger = _load(LEDGER_PATH)
    ledger["rows"].pop()
    path = tmp_path / "missing-row.json"
    path.write_bytes(rfc8785.dumps(ledger))
    with pytest.raises(ValueError, match="exact compatible unit"):
        analyzer.analyze(path)


def test_wrong_reason_falsifies_reason_sensitive_proposition(tmp_path: Path) -> None:
    analyzer = _module(ANALYZER_PATH, "dummy_analyzer_reason")
    ledger = copy.deepcopy(_load(LEDGER_PATH))
    row = next(
        item
        for item in ledger["rows"]
        if item["operator_id"] == "CONTENT-BITFLIP-001" and item["profile_id"] == "P1"
    )
    row["primary_reason"] = "OK" if row["expected_primary_reason"] != "OK" else "JSON_INVALID"
    path = tmp_path / "wrong-reason.json"
    path.write_bytes(rfc8785.dumps(ledger))
    summary = analyzer.analyze(path)
    propositions = {item["id"]: item for item in summary["propositions"]}
    assert propositions["PR-002"]["status"] == "FALSIFIED_OR_INCOMPLETE"
    assert row["row_id"] in propositions["PR-002"]["mismatch_row_ids"]


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("expected_decision", "REJECT"),
        ("expected_primary_reason", "UNREGISTERED_REASON"),
        ("target_decision", "ACCEPT"),
        ("operator_family", "post_hoc_family"),
        ("operator_kind", "clean"),
        ("stratum", "S2-PRODUCTION-SIGSTORE"),
    ],
)
def test_copied_design_labels_cannot_override_frozen_sources(
    tmp_path: Path, field: str, replacement: str
) -> None:
    analyzer = _module(ANALYZER_PATH, f"dummy_analyzer_design_{field}")
    ledger = copy.deepcopy(_load(LEDGER_PATH))
    row = next(item for item in ledger["rows"] if item["operator_kind"] == "target_invalid")
    if row[field] == replacement:
        replacement = "ACCEPT" if replacement == "REJECT" else "REJECT"
    row[field] = replacement
    path = tmp_path / f"wrong-{field}.json"
    path.write_bytes(rfc8785.dumps(ledger))
    with pytest.raises(ValueError, match="differs from frozen design"):
        analyzer.analyze(path)


def test_duplicate_composite_cell_is_rejected_even_with_new_row_id(tmp_path: Path) -> None:
    analyzer = _module(ANALYZER_PATH, "dummy_analyzer_duplicate_cell")
    ledger = copy.deepcopy(_load(LEDGER_PATH))
    duplicate = copy.deepcopy(ledger["rows"][0])
    duplicate["row_id"] += "-duplicate"
    ledger["rows"].insert(1, duplicate)
    path = tmp_path / "duplicate-cell.json"
    path.write_bytes(rfc8785.dumps(ledger))
    with pytest.raises(ValueError, match="frozen design|duplicate unit"):
        analyzer.analyze(path)


def test_profiles_must_share_the_same_generated_case_bytes(tmp_path: Path) -> None:
    analyzer = _module(ANALYZER_PATH, "dummy_analyzer_unpaired")
    ledger = copy.deepcopy(_load(LEDGER_PATH))
    row = next(
        item
        for item in ledger["rows"]
        if item["generation_status"] == "GENERATED" and item["profile_id"] == "P0"
    )
    row["case_archive_sha256"] = "0" * 64
    path = tmp_path / "unpaired.json"
    path.write_bytes(rfc8785.dumps(ledger))
    with pytest.raises(ValueError, match="profile-paired"):
        analyzer.analyze(path)


def test_profiles_must_share_case_generation_state(tmp_path: Path) -> None:
    analyzer = _module(ANALYZER_PATH, "dummy_analyzer_generation_pair")
    ledger = copy.deepcopy(_load(LEDGER_PATH))
    row = next(
        item
        for item in ledger["rows"]
        if item["generation_status"] == "GENERATED" and item["profile_id"] == "P0"
    )
    row.update(
        generation_status="GENERATION_FAILURE",
        execution_status="MISSING_EXECUTION",
        decision=None,
        primary_reason=None,
        case_archive_sha256=None,
        trust_policy_sha256=None,
    )
    path = tmp_path / "generation-unpaired.json"
    path.write_bytes(rfc8785.dumps(ledger))
    with pytest.raises(ValueError, match="disagree on case generation"):
        analyzer.analyze(path)


def test_relabeling_dummy_bytes_as_r1_cannot_self_authorize(tmp_path: Path) -> None:
    analyzer = _module(ANALYZER_PATH, "dummy_analyzer_relabel")
    ledger = copy.deepcopy(_load(LEDGER_PATH))
    ledger["classification"] = "confirmatory_R1"
    path = tmp_path / "relabelled-r1.json"
    path.write_bytes(rfc8785.dumps(ledger))
    summary = analyzer.analyze(path)
    assert summary["classification"] == "confirmatory_R1"
    assert summary["manuscript_claims_authorized"] is False
    assert summary["read_scope"]["confirmatory_artifacts_read"] is True
    assert "analysis summaries cannot self-authorize manuscript claims" in summary[
        "authorization_blockers"
    ]


def test_duplicate_json_key_is_rejected_before_analysis(tmp_path: Path) -> None:
    analyzer = _module(ANALYZER_PATH, "dummy_analyzer_duplicate")
    raw = LEDGER_PATH.read_bytes()
    duplicate = raw.replace(
        b'{"classification":"dummy_no_confirmatory_evidence",',
        b'{"classification":"dummy_no_confirmatory_evidence","classification":"dummy_no_confirmatory_evidence",',
        1,
    )
    path = tmp_path / "duplicate.json"
    path.write_bytes(duplicate)
    with pytest.raises(analyzer.DuplicateKeyError):
        analyzer.analyze(path)
