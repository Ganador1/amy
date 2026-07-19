#!/usr/bin/env python3
"""Hermetic integration tests for provenance, novelty, and paper review."""

from __future__ import annotations

import json
import multiprocessing
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from pathlib import Path

import pytest

from communication.paper_enhancer import (
    DOMAIN_INSIGHTS,
    PaperEnhancer,
    PeerReviewer,
    generate_hypothesis,
)
from core import provenance as provenance_module
from core.provenance import ProvenanceManager
from run_amy_novelty import is_known_conjecture


def _concurrent_provenance_write(args: tuple[str, int]) -> tuple[str, str]:
    """Top-level worker so the multiprocess reproduction is spawn-safe."""
    base_dir, sequence = args
    output = f"retained-output-{sequence}"
    record = ProvenanceManager(base_dir=base_dir).record_execution(
        tool_name="concurrency_probe",
        tool_input=f"input-{sequence}",
        tool_output=output,
        success=True,
        duration_seconds=sequence / 1000,
        domain="testing",
        experiment_id="shared_execution",
        extra={"sequence": sequence},
    )
    return record["experiment_id"], output


def test_provenance_manager_records_and_verifies_retained_output(tmp_path):
    manager = ProvenanceManager(base_dir=tmp_path)
    record = manager.record_execution(
        tool_name="prime_gap_analysis",
        tool_input="1000",
        tool_output=(
            "Prime gaps up to 1000: Mean gap: 6.09, "
            "Max gap: 20, Number of primes: 168"
        ),
        success=True,
        duration_seconds=0.5,
        domain="mathematics",
    )

    verification = manager.verify_experiment_id(record["experiment_id"])
    assert verification["exists"] is True
    assert verification["integrity_verified"] is True
    assert verification["authenticated"] is False
    assert verification["rollback_protected"] is False
    assert verification["truth_verified"] is False
    assert manager.verify_experiment_id("fake_nonexistent_id")["exists"] is False


def _assert_concurrent_records_are_distinct_and_intact(
    base_dir: Path,
    results: list[tuple[str, str]],
) -> None:
    assert len(results) == 20
    assert len({experiment_id for experiment_id, _ in results}) == 20

    manager = ProvenanceManager(base_dir=base_dir)
    for experiment_id, expected_output in results:
        experiment_dir = base_dir / experiment_id
        assert (experiment_dir / "output.txt").read_text(encoding="utf-8") == expected_output
        verification = manager.verify_experiment_id(experiment_id)
        assert verification["integrity_verified"] is True
        assert verification["authenticated"] is False
        assert verification["rollback_protected"] is False
        assert verification["truth_verified"] is False
        assert not list(experiment_dir.glob(".*.tmp"))


def test_record_execution_is_thread_safe_without_overwrite(tmp_path):
    args = [(str(tmp_path), sequence) for sequence in range(20)]
    with ThreadPoolExecutor(max_workers=20) as executor:
        results = list(executor.map(_concurrent_provenance_write, args))

    _assert_concurrent_records_are_distinct_and_intact(tmp_path, results)


def test_record_execution_is_multiprocess_safe_without_overwrite(tmp_path):
    args = [(str(tmp_path), sequence) for sequence in range(20)]
    context = multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(max_workers=10, mp_context=context) as executor:
        results = list(executor.map(_concurrent_provenance_write, args))

    _assert_concurrent_records_are_distinct_and_intact(tmp_path, results)


def test_failed_metadata_commit_does_not_leave_a_partial_record(monkeypatch, tmp_path):
    real_atomic_write = provenance_module._atomic_write_bytes

    def fail_metadata_write(path, content):
        if path.name == "provenance.json":
            raise OSError("simulated metadata commit failure")
        real_atomic_write(path, content)

    monkeypatch.setattr(provenance_module, "_atomic_write_bytes", fail_metadata_write)
    manager = ProvenanceManager(base_dir=tmp_path)

    with pytest.raises(OSError, match="metadata commit failure"):
        manager.record_execution(
            "atomicity_probe",
            "input",
            "output",
            True,
            0.1,
            experiment_id="partial_record",
        )

    assert not (tmp_path / "partial_record").exists()


def test_integrity_verification_rejects_record_field_tampering(tmp_path):
    mutations = [
        ("timestamp", lambda record: record.__setitem__("timestamp", "1999-01-01T00:00:00Z")),
        ("experiment_id", lambda record: record.__setitem__("experiment_id", "forged_id")),
        ("tool_name", lambda record: record["tool"].__setitem__("name", "forged_tool")),
        ("tool_input", lambda record: record["tool"].__setitem__("input", "forged input")),
        ("output_hash", lambda record: record["tool"].__setitem__("output_hash", "0" * 64)),
        ("output_length", lambda record: record["tool"].__setitem__("output_length", 999)),
        ("output_size", lambda record: record["tool"].__setitem__("output_size_bytes", 999)),
        ("success", lambda record: record["tool"].__setitem__("success", False)),
        ("duration", lambda record: record["tool"].__setitem__("duration_seconds", 999.0)),
        ("preview", lambda record: record.__setitem__("output_preview", "forged preview")),
        ("domain", lambda record: record.__setitem__("domain", "forged-domain")),
        ("environment", lambda record: record["environment"].__setitem__("hostname", "forged-host")),
        ("extra", lambda record: record["extra"].__setitem__("seed", 999)),
        ("version", lambda record: record.__setitem__("provenance_version", "9.9")),
        ("algorithm", lambda record: record["integrity"].__setitem__("algorithm", "sha1")),
        ("scope", lambda record: record["integrity"].__setitem__("scope", "output only")),
        ("authenticated", lambda record: record["integrity"].__setitem__("authenticated", True)),
        (
            "rollback",
            lambda record: record["integrity"].__setitem__("rollback_protected", True),
        ),
        ("truth", lambda record: record["integrity"].__setitem__("truth_verified", True)),
        ("record_hash", lambda record: record["integrity"].__setitem__("record_hash", "0" * 64)),
    ]

    for label, mutate in mutations:
        case_dir = tmp_path / label
        manager = ProvenanceManager(base_dir=case_dir)
        recorded = manager.record_execution(
            tool_name="tamper_probe",
            tool_input="seed=7",
            tool_output="measured value = 42",
            success=True,
            duration_seconds=0.125,
            domain="testing",
            experiment_id="tamper_case",
            extra={"seed": 7},
        )
        provenance_path = case_dir / recorded["experiment_id"] / "provenance.json"
        on_disk = json.loads(provenance_path.read_text(encoding="utf-8"))
        mutate(on_disk)
        provenance_path.write_text(
            json.dumps(on_disk, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        verification = manager.verify_experiment_id(recorded["experiment_id"])
        assert verification["exists"] is True
        assert verification["integrity_verified"] is False, label
        assert verification["authenticated"] is False
        assert verification["rollback_protected"] is False
        assert verification["truth_verified"] is False


def test_integrity_verification_rejects_retained_output_tampering(tmp_path):
    manager = ProvenanceManager(base_dir=tmp_path)
    record = manager.record_execution(
        "tamper_probe",
        "input",
        "original output",
        True,
        0.1,
        experiment_id="output_tamper_case",
    )
    output_path = tmp_path / record["experiment_id"] / "output.txt"
    output_path.write_text("forged output", encoding="utf-8")

    verification = manager.verify_experiment_id(record["experiment_id"])
    assert verification["exists"] is True
    assert verification["integrity_verified"] is False
    assert verification["authenticated"] is False
    assert verification["rollback_protected"] is False
    assert verification["truth_verified"] is False


def test_known_conjecture_filter_separates_canonical_and_candidate_claims():
    cases = [
        ("Goldbach conjecture: every even integer > 2 is the sum of two primes", True),
        ("Twin prime conjecture: infinitely many twin primes", True),
        ("Collatz conjecture: 3n+1 problem eventually reaches 1", True),
        ("Riemann hypothesis: all non-trivial zeros of zeta(s)", True),
        ("The Cramér model overestimates max prime gaps by factor 2.3x", False),
        ("HOMO-LUMO gap scales as 4.95/n + 1.15", False),
    ]

    for text, expected in cases:
        assert is_known_conjecture(text) is expected


def test_peer_review_requires_integrity_checked_provenance(tmp_path):
    manager = ProvenanceManager(base_dir=tmp_path)
    record = manager.record_execution(
        "prime_gap_analysis",
        "1000",
        "Mean gap: 6.09",
        True,
        0.5,
        domain="mathematics",
        experiment_id="exp_real",
    )
    reviewer = PeerReviewer(provenance_manager=manager)
    common = {
        "domain": "mathematics",
        "topic": "Prime Gap Analysis",
        "results": [
            {
                "tool": "prime_gap_analysis",
                "success": True,
                "result": "Mean gap: 6.09",
            }
        ],
        "sections": [{"heading": "Results", "content": "experiment data"}],
        "hypotheses": [
            {
                "hypothesis": "Test",
                "confidence": 0.7,
                "testable": True,
                "method": "Test",
            }
        ],
        "references": ["Ref1", "Ref2", "Ref3"],
    }

    real = reviewer.review_paper(
        **common, experiment_ids=[record["experiment_id"]]
    )
    fake = reviewer.review_paper(**common, experiment_ids=["fake_id_1"])

    assert (
        real["scores"]["reproducibility"]
        > fake["scores"]["reproducibility"]
    )
    assert "unauthenticated" in " ".join(real["feedback"])


def test_hypothesis_generation_deduplicates_same_tool_type():
    same_tool = [
        {
            "tool": "prime_gap_analysis",
            "success": True,
            "result": f"Mean gap: {value}",
        }
        for value in ("6.09", "8.12", "9.15")
    ]
    different_tools = [
        {"tool": "prime_gap_analysis", "success": True, "result": "Mean gap: 6.09"},
        {"tool": "sympy_derivative", "success": True, "result": "f'(x) = 3x²"},
        {
            "tool": "number_theory_advanced",
            "success": True,
            "result": "Goldbach verified",
        },
    ]

    assert len(generate_hypothesis("mathematics", same_tool)) <= 1
    assert len(generate_hypothesis("mathematics", different_tools)) >= 2


def test_molecular_orbital_discussion_matches_tool_semantics():
    discussion = PaperEnhancer()._build_discussion(
        "chemistry",
        [
            {
                "tool": "molecular_orbital_energy",
                "success": True,
                "result": "HOMO: -4.887 eV, LUMO: -7.113 eV",
                "description": "4-carbon system",
            }
        ],
        DOMAIN_INSIGHTS["chemistry"],
    )

    assert "Hückel" in discussion or "HOMO" in discussion or "orbital" in discussion.lower()
    assert "molecular weight" not in discussion.lower()
    assert "stoichiometric" not in discussion.lower()
