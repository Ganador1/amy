from __future__ import annotations

import importlib.util
import json
from pathlib import Path


STUDY_ROOT = Path(__file__).resolve().parents[1]


def _load_script(name: str):
    path = STUDY_ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_retained_system_paper_audit_replays_and_accounting_closes(monkeypatch):
    scanner = _load_script("audit_system_paper_integrity")
    monkeypatch.syspath_prepend(str(STUDY_ROOT / "scripts"))
    validator = _load_script("validate_system_paper_audit")
    result = validator.validate(
        STUDY_ROOT / "audit/AMY_SYSTEM_PAPER_DEEP_AUDIT_RAW_2026-07-13.json",
        scanner.DEFAULT_REPOSITORY_ROOT,
        scanner.DEFAULT_PAPER_WORKTREE,
    )
    assert result["valid"], result["errors"]
    assert result["source_drift_detected"] is (
        not result["byte_identical_after_canonicalization"]
    )


def test_system_paper_audit_separates_historical_release_from_dirty_revision():
    audit = json.loads(
        (
            STUDY_ROOT
            / "audit/AMY_SYSTEM_PAPER_DEEP_AUDIT_RAW_2026-07-13.json"
        ).read_text(encoding="utf-8")
    )
    integrity = audit["release_integrity"]
    schema = audit["benchmark"]["response_and_schema_audit"]
    transport = audit["benchmark"]["transport_record"]
    generation = audit["static_pipeline"]["generation_chain"]
    analysis_freeze = audit["static_pipeline"]["analysis_freeze"]
    unsupported = audit["benchmark"]["recomputed_inference"]["secondary"][
        "unsupported_decimal_present"
    ]

    assert integrity["committed_head"]["manifest"]["valid"] is True
    assert integrity["current_worktree"]["manifest"]["valid"] is False
    assert len(integrity["current_worktree"]["manifest"]["mismatches"]) == 13
    assert schema["exact_response_contents"] == 540
    assert schema["unique_exact_response_contents"] == 540
    assert len(schema["strict_schema_type_violations"]) == 1
    assert schema["abstract_word_range_violations"] == 27
    assert schema["conclusion_word_range_violations"] == 22
    assert transport["request_artifacts_with_max_tokens"] == 0
    assert transport["response_artifacts_with_model_digest"] == 0
    assert transport["response_artifacts_with_server_version"] == 0
    assert generation["reused_evidence_output_digest_recomputed_before_use"] is False
    assert generation["resume_revalidates_existing_request_and_response_bytes"] is False
    assert generation["missing_or_blank_response_model_is_accepted"] is True
    assert analysis_freeze["analysis_methods_declared_in_preregistration"] is True
    assert analysis_freeze["executable_analysis_frozen_before_first_response"] is False
    assert unsupported["holm_adjusted_pair_level_pvalue"] < 0.05
    assert unsupported["case_cluster_sensitivity"]["exact_two_sided_sign_flip_pvalue"] > 0.05
    assert unsupported["domain_cluster_sensitivity"]["exact_two_sided_sign_flip_pvalue"] > 0.05
    assert audit["overall_assessment"]["fit_for_citation_as_confirmatory_scientific_evidence"] is False


def test_missing_system_paper_worktree_fails_closed(tmp_path: Path):
    scanner = _load_script("audit_system_paper_integrity")
    repository = tmp_path / "repository"
    repository.mkdir()

    audit = scanner.build_audit(repository, repository / ".worktrees/missing")

    assert audit["replay_status"]["complete"] is False
    assert audit["replay_status"]["missing_required_inputs"]
    assert audit["replay_status"]["absence_treated_as_success"] is False
    assert audit["replay_status"]["scientific_claims_authorized"] is False
    assert audit["overall_assessment"][
        "fit_for_citation_as_confirmatory_scientific_evidence"
    ] is False
