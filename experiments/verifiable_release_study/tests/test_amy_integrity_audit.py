from __future__ import annotations

import importlib.util
from pathlib import Path


STUDY_ROOT = Path(__file__).resolve().parents[1]


def _load_script(name: str):
    path = STUDY_ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_retained_amy_audit_is_valid_and_current_drift_is_disclosed(monkeypatch):
    scanner = _load_script("audit_amy_integrity")
    monkeypatch.syspath_prepend(str(STUDY_ROOT / "scripts"))
    validator = _load_script("validate_amy_audit")
    result = validator.validate(
        STUDY_ROOT / "audit/AMY_DEEP_AUDIT_RAW_2026-07-13.json",
        scanner.DEFAULT_REPOSITORY_ROOT,
    )
    assert result["valid"], result["errors"]
    assert result["byte_identical_after_canonicalization"] is False
    assert result["current_replay_matches_retained"] is False
    assert result["source_drift_detected"] is True


def test_amy_audit_keeps_integrity_authentication_and_truth_separate():
    scanner = _load_script("audit_amy_integrity")
    audit = scanner.build_audit(scanner.DEFAULT_REPOSITORY_ROOT)
    summary = audit["directory_provenance"]["summary"]
    facts = audit["static_code"]["source_facts"]
    assert summary["stored_output_sha256_matches_current_bytes"] == summary[
        "provenance_records"
    ]
    assert summary["authenticated_records"] == 0
    assert facts["active_provenance_manager_calls_sign_provenance"] is False
    assert facts["paper_gate_calls_verify_provenance"] is False
    assert facts["paper_gate_hash_reader_recomputes_sha256"] is False
    assert facts[
        "numeric_verifier_treats_nonempty_experiment_id_list_as_explicit_provenance"
    ] is True
    assert audit["trust_boundary"]["scientific_truth"] == (
        "never inferred from a matching digest or signature"
    )
