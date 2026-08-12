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


def test_retained_axiom_audit_is_valid_and_current_drift_is_disclosed(monkeypatch):
    scanner = _load_script("audit_axiom_integrity")
    monkeypatch.syspath_prepend(str(STUDY_ROOT / "scripts"))
    validator = _load_script("validate_axiom_audit")
    result = validator.validate(
        STUDY_ROOT / "audit/AXIOM_DEEP_AUDIT_RAW_2026-07-13.json",
        scanner.DEFAULT_REPOSITORY_ROOT,
    )
    assert result["valid"], result["errors"]
    assert result["byte_identical_after_canonicalization"] is False
    assert result["current_replay_matches_retained"] is False
    assert result["source_drift_detected"] is True


def test_axiom_audit_separates_brand_labels_from_scientific_evidence():
    scanner = _load_script("audit_axiom_integrity")
    current = scanner.build_audit(scanner.DEFAULT_REPOSITORY_ROOT)
    retained = json.loads(
        (
            STUDY_ROOT / "audit/AXIOM_DEEP_AUDIT_RAW_2026-07-13.json"
        ).read_text(encoding="utf-8")
    )
    boundary = current["project_boundary"]["independent_axiom_surface"]
    deployment = current["project_boundary"]["deployment"]
    summary = retained["axiom_named_json_artifacts"]["summary"]
    critical = retained["critical_claim_checks"]

    assert boundary["top_level_axiom_python_package_exists"] is False
    assert boundary["console_entry_point_count"] == 0
    assert len(boundary["route_string_literals_starting_with_axiom"]) == 0
    assert deployment["docker_entry_point"] == "main:app"
    assert deployment["docker_entry_point_has_direct_syntax_blocker"] is True
    assert len(deployment["direct_import_syntax_blockers"]) == 2
    assert summary["scientific_or_claim_artifacts"] == 11
    assert summary["scientific_artifacts_with_authentication_fields"] == 0
    assert summary["scientific_artifacts_with_content_digest_fields"] == 0
    assert summary["scientific_artifacts_with_source_revision_fields"] == 0
    assert critical["failed_upstream_but_final_true"]["contradiction_count"] == 3
    assert critical["zero_data_positive_reports"]["count"] == 2
    assert critical["literal_multidomain_real_data_demo"][
        "real_data_examples_exactly_equal_source_return_literal"
    ] is True
    assert critical["literal_multidomain_real_data_demo"]["producer_network_call_count"] == 0
    assert retained["trust_boundary"]["scientific_truth"] == (
        "never inferred from labels, successful HTTP status, digests, signatures, or generated prose"
    )
    assert current["axiom_named_json_artifacts"]["summary"][
        "scientific_or_claim_artifacts"
    ] <= summary["scientific_or_claim_artifacts"]
    complete_path = (
        scanner.DEFAULT_REPOSITORY_ROOT
        / "atlas/artifacts/demos/axiom_complete_demo_20250921_213324.json"
    )
    assert (
        current["critical_claim_checks"]["failed_upstream_but_final_true"][
            "artifact_sha256"
        ]
        is not None
    ) is complete_path.is_file()
