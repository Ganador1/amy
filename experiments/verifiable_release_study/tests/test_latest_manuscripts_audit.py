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


def test_retained_latest_manuscripts_audit_is_valid_and_drift_is_disclosed(monkeypatch):
    scanner = _load_script("audit_latest_manuscripts")
    monkeypatch.syspath_prepend(str(STUDY_ROOT / "scripts"))
    validator = _load_script("validate_latest_manuscripts_audit")
    result = validator.validate(
        STUDY_ROOT / "audit/LATEST_MANUSCRIPTS_DEEP_AUDIT_RAW_2026-07-13.json",
        scanner.DEFAULT_REPOSITORY_ROOT,
        scanner.DEFAULT_PAPER_WORKTREE,
    )
    assert result["valid"], result["errors"]
    assert result["byte_identical_after_canonicalization"] is False
    assert result["current_replay_matches_retained"] is False
    assert result["source_drift_detected"] is True


def test_latest_manuscript_exclusion_boundaries_are_explicit():
    audit = json.loads(
        (
            STUDY_ROOT
            / "audit/LATEST_MANUSCRIPTS_DEEP_AUDIT_RAW_2026-07-13.json"
        ).read_text(encoding="utf-8")
    )

    amy = audit["amy_revised_benchmark"]
    assert amy["exact_source_data_path_count"] == 24
    assert amy["all_current_replication_prefix_records"] == 96
    assert amy["prefix_is_an_unambiguous_24_record_selector"] is False
    assert amy["provenance_summary"]["preview_hash_matches"] == 24
    assert amy["provenance_summary"]["authentication_fields"] == 0
    assert amy["reference_audit"]["stodden_year_matches_official_record"] is False

    atlas = audit["atlas_system_paper"]
    assert atlas["preserved_candidate_result_artifacts"] == []
    assert atlas["reference_section_is_placeholder"] is True

    axiom = audit["axiom_meta4_paper"]
    assert axiom["all_three_are_byte_identical"] is True
    assert axiom["appendix_placeholder_count"] == 11
    assert not any(axiom["supporting_json_contains_claimed_scores"].values())

    dna = audit["amy_latest_dna_paper"]
    assert dna["missing_declared_artifact_count"] == 4
    assert dna["literal_reasoning_tag_leaks"] == 1
    assert dna["duplicated_discussion_anchor_count"] == 2
    assert dna["e2_and_e3_are_measurements_of_same_sequence"] is False
    assert dna["closest_literature_audit"][
        "declared_novelty_audit_artifact_present"
    ] is False
    assert dna["pdf_visual_review"]["review_applies_to_current_pdf_bytes"] is True
    assert dna["pdf_visual_review"]["content_equivalent_to_markdown"] is False

    bond = audit["atlas_bond_energy_paper"]
    assert bond["provenance_summary"]["preview_hash_matches"] == 8
    assert bond["provenance_summary"]["environment_present"] == 0
    assert bond["source_characteristics"]["tool_is_a_literal_lookup_table"] is True

    references = audit["formal_system_paper_references"]
    assert references["bibliography_entry_count"] == 14
    assert references["undefined_citations"] == []
    assert references["uncited_bibliography_entries"] == []
    assert references["metadata_discrepancies"][0]["authors_match"] is False

    assert audit["overall_assessment"][
        "legacy_manuscripts_fit_as_positive_scientific_evidence"
    ] is False


def test_missing_current_manuscript_inputs_fail_closed(tmp_path: Path):
    scanner = _load_script("audit_latest_manuscripts")
    repository = tmp_path / "repository"
    paper_worktree = tmp_path / "paper-worktree"
    repository.mkdir()
    paper_worktree.mkdir()

    audit = scanner.build_audit(repository, paper_worktree)

    assert audit["replay_status"]["complete"] is False
    assert audit["replay_status"]["missing_required_inputs"]
    assert audit["replay_status"]["absence_treated_as_success"] is False
    assert audit["replay_status"]["scientific_claims_authorized"] is False
    assert audit["findings"] == []
