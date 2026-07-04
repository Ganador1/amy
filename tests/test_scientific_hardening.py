#!/usr/bin/env python3
"""Regression tests for audit, provenance, and novelty hardening.

Run with:
    .venv/bin/python test_scientific_hardening.py
"""
import hashlib
import asyncio
import json
import shutil
import urllib.error
from pathlib import Path

import audit_papers
from communication.paper_enhancer import (
    DOMAIN_INSIGHTS,
    PeerReviewer,
    PaperEnhancer,
    _filter_ungrounded_hypotheses,
    _strengthen_branch_contract,
    generate_hypothesis,
    generate_references,
)
from communication.paper_generator import PaperGenerator
from communication.citation_verifier import CitationVerifier
from communication.llm_enhancer import _drop_unsupported_numeric_sentences
from core.atlas_tools import assess_tool_output
from core.provenance import ProvenanceManager
from run_amy_novelty import (
    molecular_orbital_novelty,
    prime_gap_novelty,
    quantum_scaling_novelty,
)


TMP_DIR = Path("data/experiments/test_audit_tmp")
TMP_PAPER = Path("papers/test_modern_provenance_audit.md")


def _reset_tmp():
    shutil.rmtree(TMP_DIR, ignore_errors=True)
    TMP_PAPER.unlink(missing_ok=True)
    TMP_DIR.mkdir(parents=True, exist_ok=True)


def test_audit_recognizes_modern_provenance_paths_and_hashes():
    _reset_tmp()
    exp_id = "test_audit_tmp"
    exp_dir = TMP_DIR
    exp_dir.mkdir(parents=True, exist_ok=True)
    output = "Prime gaps up to 1000\nMean gap: 5.9581\nMax gap: 20\n"
    (exp_dir / "output.txt").write_text(output, encoding="utf-8")
    output_hash = hashlib.sha256(output.encode("utf-8")).hexdigest()
    (exp_dir / "provenance.json").write_text(
        json.dumps(
            {
                "experiment_id": exp_id,
                "tool": {
                    "name": "prime_gap_analysis",
                    "input": "1000",
                    "output_hash": output_hash,
                    "success": True,
                },
                "domain": "mathematics",
                "provenance_version": "1.0",
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    TMP_PAPER.write_text(
        "\n".join(
            [
                "# Test Paper",
                "",
                "## Results",
                "Mean gap: 5.9581.",
                "",
                "## Data Availability",
                f"- {exp_id}: `{exp_dir}/provenance.json` (output SHA-256: `{output_hash}`)",
                "",
                "## References",
                "[1] Cramer, H. (1936). On the order of magnitude of the difference between consecutive primes.",
            ]
        ),
        encoding="utf-8",
    )

    result = audit_papers.audit_paper(TMP_PAPER)

    assert result["experiment_ids"] == [exp_id]
    assert result["provenance_ok"] is True
    assert result["cited_hash_ok"] is True
    assert result["provenance_hash_ok"] is True
    assert result["references_count"] == 1
    assert result["overall_score"] >= 85


def test_audit_rejects_mismatched_paper_cited_hash():
    _reset_tmp()
    exp_id = "test_audit_tmp"
    output = "Prime gaps up to 1000\nMean gap: 5.9581\nMax gap: 20\n"
    (TMP_DIR / "output.txt").write_text(output, encoding="utf-8")
    output_hash = hashlib.sha256(output.encode("utf-8")).hexdigest()
    (TMP_DIR / "provenance.json").write_text(
        json.dumps(
            {
                "experiment_id": exp_id,
                "tool": {
                    "name": "prime_gap_analysis",
                    "input": "1000",
                    "output_hash": output_hash,
                    "success": True,
                },
                "domain": "mathematics",
                "provenance_version": "1.0",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    fake_hash = "0" * 64
    TMP_PAPER.write_text(
        "\n".join(
            [
                "# Test Paper",
                "",
                "## Data Availability",
                f"- {exp_id}: `{TMP_DIR}/provenance.json` (output SHA-256: `{fake_hash}`)",
            ]
        ),
        encoding="utf-8",
    )

    result = audit_papers.audit_paper(TMP_PAPER)

    assert result["cited_hash_ok"] is False
    assert result["provenance_hash_ok"] is False
    assert result["cited_hash_details"][exp_id]["status"] == "mismatch"


def test_audit_verifies_all_modern_provenance_hashes_not_just_first_two():
    _reset_tmp()
    exp_ids = ["test_audit_tmp_a", "test_audit_tmp_b", "test_audit_tmp_c"]
    lines = ["# Test Paper", "", "## Data Availability"]
    for exp_id in exp_ids:
        exp_dir = Path("data/experiments") / exp_id
        shutil.rmtree(exp_dir, ignore_errors=True)
        exp_dir.mkdir(parents=True, exist_ok=True)
        output = f"output for {exp_id}"
        (exp_dir / "output.txt").write_text(output, encoding="utf-8")
        output_hash = hashlib.sha256(output.encode("utf-8")).hexdigest()
        (exp_dir / "provenance.json").write_text(
            json.dumps(
                {
                    "experiment_id": exp_id,
                    "tool": {
                        "name": "test_tool",
                        "input": exp_id,
                        "output_hash": output_hash,
                        "success": True,
                    },
                    "domain": "mathematics",
                    "provenance_version": "1.0",
                }
            ),
            encoding="utf-8",
        )
        lines.append(
            f"- {exp_id}: `data/experiments/{exp_id}/provenance.json` "
            f"(output SHA-256: `{output_hash}`)"
        )

    (Path("data/experiments") / exp_ids[2] / "output.txt").write_text(
        "tampered output",
        encoding="utf-8",
    )
    TMP_PAPER.write_text("\n".join(lines), encoding="utf-8")

    try:
        result = audit_papers.audit_paper(TMP_PAPER)

        assert set(result["reproducibility"]) == set(exp_ids)
        assert result["reproducibility"][exp_ids[2]]["output_hash_ok"] is False
        assert result["provenance_hash_ok"] is False
    finally:
        for exp_id in exp_ids:
            shutil.rmtree(Path("data/experiments") / exp_id, ignore_errors=True)


def test_paper_generator_cites_real_full_provenance_output_hash():
    _reset_tmp()
    exp_id = "test_audit_tmp"
    output = "tool output"
    output_hash = hashlib.sha256(output.encode("utf-8")).hexdigest()
    (TMP_DIR / "output.txt").write_text(output, encoding="utf-8")
    (TMP_DIR / "provenance.json").write_text(
        json.dumps(
            {
                "experiment_id": exp_id,
                "tool": {
                    "name": "test_tool",
                    "input": "x",
                    "output_hash": output_hash,
                    "success": True,
                },
                "domain": "mathematics",
                "provenance_version": "1.0",
            }
        ),
        encoding="utf-8",
    )

    markdown = PaperGenerator(enhance=False)._build_markdown(
        "Test Paper",
        "Abstract.",
        [{"heading": "Methods", "content": "Method."}],
        [],
        [],
        [exp_id],
    )

    assert f"output SHA-256: `{output_hash}`" in markdown
    assert "0/10" not in markdown


def test_paper_generator_watermark_does_not_claim_embedded_self_review_by_default():
    markdown = PaperGenerator(enhance=False)._append_watermark("Body", "Test Paper")

    assert "Self-Review (Reflection Agent) section above" not in markdown
    assert "self_review: external_sidecar_when_available" in markdown


def test_paper_generator_detects_machine_learning_domain():
    markdown = PaperGenerator(enhance=False)._build_markdown(
        "Information Bottleneck Benchmark for a ReLU Neural Network",
        "Abstract.",
        [{"heading": "Methods", "content": "Held-out label-shuffled representation learning benchmark."}],
        [],
        [],
        ["machine-learning_example_20260527"],
    )

    assert "ACM CCS" in markdown
    assert "information bottleneck" in markdown.lower()


def test_objective_scorer_accepts_hyphenated_experiment_ids():
    from experiments.ab_test.scoring.score_paper import score_paper

    exp_id = "machine-learning_test_tool_20260527_120000"
    exp_dir = Path("data/experiments") / exp_id
    paper_path = Path("papers/test_hyphenated_score.md")
    shutil.rmtree(exp_dir, ignore_errors=True)
    paper_path.unlink(missing_ok=True)

    output = json.dumps({"accuracy": 0.8123, "p": 0.0123, "summary": "held-out benchmark"})
    output_hash = hashlib.sha256(output.encode("utf-8")).hexdigest()
    exp_dir.mkdir(parents=True, exist_ok=True)
    (exp_dir / "output.txt").write_text(output, encoding="utf-8")
    (exp_dir / "provenance.json").write_text(
        json.dumps(
            {
                "experiment_id": exp_id,
                "tool": {"name": "test_tool", "output_hash": output_hash, "success": True},
                "domain": "machine-learning",
            }
        ),
        encoding="utf-8",
    )
    paper_path.write_text(
        (
            "# Test\n\n"
            "**Classification:** Machine learning\n\n"
            "## Abstract\n\naccuracy 0.8123.\n\n"
            "## Discussion\n\nThis study does not claim causality. "
            "The result reports p=0.0123 and 95% CI [0.7, 0.9].\n\n"
            "### Testable Predictions\n\n"
            "H1. Testable via rerun: accuracy should remain positive; confidence: 70%.\n\n"
            "## Data Availability\n\n"
            f"- {exp_id}: `data/experiments/{exp_id}/provenance.json` "
            f"(output SHA-256: `{output_hash}`)\n"
        ),
        encoding="utf-8",
    )

    try:
        score = score_paper(paper_path)
        assert score.domain == "machine-learning"
        assert score.provenance_integrity == 10.0
        assert score.numerical_claims_grounded > 0
        assert score.falsifiability > 0
    finally:
        shutil.rmtree(exp_dir, ignore_errors=True)
        paper_path.unlink(missing_ok=True)


def test_paper_generator_rejects_publication_when_provenance_hash_is_missing():
    title = "Test Missing Provenance Gate"

    result = asyncio.run(
        PaperGenerator(enhance=False).generate_paper(
            title=title,
            abstract="Abstract.",
            sections=[{"heading": "Methods", "content": "Method."}],
            references=[],
            knowledge_facts=[],
            experiment_ids=["missing_experiment_for_gate"],
        )
    )

    path = Path(result["markdown_path"])
    try:
        assert result["publication_status"] == "rejected"
        assert "missing provenance output hash" in result["rejection_reasons"]
        assert path.parent.name == "rejected"
        assert result["pdf_path"] is None
    finally:
        path.unlink(missing_ok=True)


def test_paper_generator_prepublication_gate_rejects_plain_unusable_output():
    gate = PaperGenerator(enhance=False)._prepublication_gate(
        "## Results\nMolecular weight of He: 0.000 g/mol\nComposition:",
        [],
    )

    assert gate["passed"] is False
    assert "unusable tool output in manuscript" in gate["reasons"]


def test_audit_does_not_treat_sha256_chunks_as_experiment_ids():
    text = (
        "- exp_real: `data/experiments/exp_real/provenance.json`\n"
        "Script SHA-256: `5a690e0368d1c633957dda6eed8e5845c4e0807a4302cdeb3ae751f62862e3d5`"
    )

    assert audit_papers.extract_experiment_ids(text) == ["exp_real"]


def test_citation_verifier_strips_trailing_doi_punctuation():
    citations = CitationVerifier().extract_citations(
        "A sentence citation (doi: 10.1038/s41586-026-10265-5)."
    )

    assert citations == [{"type": "doi", "raw": "10.1038/s41586-026-10265-5"}]


def test_citation_verifier_falls_back_to_crossref_when_publisher_blocks_doi(monkeypatch):
    class FakeResponse:
        url = "https://api.crossref.org/works/10.1021%2Fed084p1840"

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def getcode(self):
            return 200

        def read(self):
            return b'{"status":"ok","message":{"DOI":"10.1021/ed084p1840"}}'

    def fake_urlopen(req, timeout=15):
        url = req.full_url
        if url.startswith("https://doi.org/"):
            raise urllib.error.HTTPError(url, 403, "Forbidden", hdrs=None, fp=None)
        if url.startswith("https://api.crossref.org/works/"):
            return FakeResponse()
        raise AssertionError(f"unexpected URL {url}")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    result = CitationVerifier().verify_doi("10.1021/ed084p1840")

    assert result["verified"] is True
    assert result["source"] == "crossref"


def test_unknown_operation_output_is_not_scientific_evidence():
    assessment = assess_tool_output("Unknown operation: derivative. Available: limit, taylor")

    assert assessment["usable"] is False
    assert "unknown operation" in assessment["markers"]


def test_error_output_is_not_scientific_evidence():
    assessment = assess_tool_output(
        "Error: Format should be 'operation:arg'. Received: '1000003'",
        tool_name="sympy_prime_analysis",
    )

    assert assessment["usable"] is False
    assert "error:" in assessment["markers"]


def test_metric_names_containing_error_are_scientific_evidence():
    assessment = assess_tool_output(
        "Formula check max_abs_error: 6.661e-16 eV\nBest model by RMSE: power_law",
        tool_name="huckel_polyene_scaling",
    )

    assert assessment["usable"] is True
    assert assessment["markers"] == []


def test_zero_molecular_weight_output_is_not_scientific_evidence():
    assessment = assess_tool_output("Molecular weight of He: 0.000 g/mol\nComposition:")

    assert assessment["usable"] is False
    assert "zero molecular weight" in assessment["markers"]


def test_chemistry_polyene_scaling_references_include_huckel_sources():
    refs = generate_references(
        "chemistry",
        [{"tool": "huckel_polyene_scaling", "success": True}],
    )

    assert any("Hückel" in ref or "Huckel" in ref for ref in refs)
    assert any("Autschbach" in ref for ref in refs)


def test_chemistry_ssh_gap_map_references_include_ssh_sources():
    refs = generate_references(
        "chemistry",
        [{"tool": "ssh_polyene_gap_map", "success": True}],
    )

    assert any("Su" in ref and "Schrieffer" in ref and "Heeger" in ref for ref in refs)
    assert any("polyacetylene" in ref.lower() for ref in refs)


def test_bond_alternated_polyene_hypothesis_uses_recorded_gap_not_generic_bond_claim():
    hypotheses = generate_hypothesis(
        "chemistry",
        [
            {
                "tool": "bond_alternated_polyene_scaling",
                "result": (
                    "Bond-alternated polyene gap scaling:\n"
                    "  asymptotic_gap_estimate = 0.800000 eV\n"
                    "  n=100: alternated_gap=0.846601 eV\n"
                ),
                "success": True,
            }
        ],
    )
    combined = "\n".join(h["hypothesis"] + " " + h["method"] for h in hypotheses)

    assert "0.800000 eV" in combined
    assert "catalysis" not in combined.lower()
    assert "4|" not in combined


def test_ssh_polyene_gap_map_hypothesis_targets_identifiability_not_generic_gap():
    hypotheses = generate_hypothesis(
        "chemistry",
        [
            {
                "tool": "ssh_polyene_gap_map",
                "result": (
                    "SSH/polyene finite-chain gap map:\n"
                    "  identifiability_threshold_eV=0.050000\n"
                    "  delta=0.050000: smallest_identifiable_n=20\n"
                    "  orientation=topological; edge_state_warning=true; "
                    "edge_state_onset_n=40; "
                    "frontier_gap=0.012000 eV; peierls_bulk_gap_estimate=0.500000 eV\n"
                ),
                "success": True,
            }
        ],
    )
    combined = "\n".join(h["hypothesis"] + " " + h["method"] for h in hypotheses)

    assert "smallest_identifiable_n=20" in combined
    assert "edge_state_onset_n=40" in combined
    assert "edge-state" in combined.lower() or "edge state" in combined.lower()
    assert "identifiability" in combined.lower()
    assert "catalysis" not in combined.lower()


def test_ssh_polyene_gap_map_hypothesis_ignores_zero_delta_control_rows():
    hypotheses = generate_hypothesis(
        "chemistry",
        [
            {
                "tool": "ssh_polyene_gap_map",
                "result": (
                    "SSH/polyene finite-chain gap map:\n"
                    "  identifiability_threshold_eV=0.050000\n"
                    "  Identifiability summary:\n"
                    "  delta=0.000000; orientation=trivial; "
                    "smallest_identifiable_n=not_identified; "
                    "edge_state_onset_n=not_observed; "
                    "terminal_gap_n100=0.155518 eV; "
                    "peierls_bulk_gap_estimate=0.000000 eV\n"
                    "  delta=0.000000; orientation=topological; "
                    "smallest_identifiable_n=not_identified; "
                    "edge_state_onset_n=not_observed; "
                    "terminal_gap_n100=0.155518 eV; "
                    "peierls_bulk_gap_estimate=0.000000 eV\n"
                    "  delta=0.025000; orientation=trivial; "
                    "smallest_identifiable_n=4; "
                    "edge_state_onset_n=not_observed; "
                    "terminal_gap_n100=0.343804 eV; "
                    "peierls_bulk_gap_estimate=0.250000 eV\n"
                    "  delta=0.025000; orientation=topological; "
                    "smallest_identifiable_n=4; "
                    "edge_state_onset_n=60; "
                    "terminal_gap_n100=0.041140 eV; "
                    "peierls_bulk_gap_estimate=0.250000 eV\n"
                ),
                "success": True,
            }
        ],
    )
    combined = "\n".join(h["hypothesis"] + " " + h["method"] for h in hypotheses)

    assert "delta=0.025000" in combined
    assert "smallest_identifiable_n=4" in combined
    assert "edge_state_onset_n=60" in combined
    assert "delta=0.000000, smallest_identifiable_n=not_identified" not in combined
    assert "edge_state_onset_n=not_observed" not in combined


def test_provenance_manager_does_not_overwrite_same_second_tool_runs():
    _reset_tmp()
    manager = ProvenanceManager(base_dir=TMP_DIR)

    first = manager.record_execution(
        tool_name="quantum_energy_levels",
        tool_input="hydrogen:1",
        tool_output="E1",
        success=True,
        duration_seconds=0.1,
        domain="physics",
        experiment_id="physics_quantum_energy_levels_collision",
    )
    second = manager.record_execution(
        tool_name="quantum_energy_levels",
        tool_input="hydrogen:2",
        tool_output="E2",
        success=True,
        duration_seconds=0.1,
        domain="physics",
        experiment_id="physics_quantum_energy_levels_collision",
    )

    assert first["experiment_id"] == "physics_quantum_energy_levels_collision"
    assert second["experiment_id"] == "physics_quantum_energy_levels_collision_2"
    assert (TMP_DIR / first["experiment_id"] / "output.txt").read_text(encoding="utf-8") == "E1"
    assert (TMP_DIR / second["experiment_id"] / "output.txt").read_text(encoding="utf-8") == "E2"


def test_audit_flags_zero_failure_claim_with_failed_tool_output():
    text = "\n".join(
        [
            "# Test Paper",
            "All results are real experimental outputs with zero tool failures.",
            "## Results",
            "```",
            "Unknown operation: derivative. Available: limit, taylor",
            "```",
        ]
    )

    result = audit_papers.detect_operational_output_issues(text)

    assert result["zero_failure_claim"] is True
    assert result["unusable_output_blocks"]
    assert "claims_zero_failures_but_contains_unusable_tool_output" in result["contradictions"]


def test_audit_flags_zero_molecular_weight_in_plain_result_text():
    text = "\n".join(
        [
            "# Test Paper",
            "## Results",
            "Molecular weight of He: 0.000 g/mol",
            "Composition:",
        ]
    )

    result = audit_papers.detect_operational_output_issues(text)

    assert result["unusable_output_blocks"]
    assert "zero molecular weight" in result["unusable_output_blocks"][0]["markers"]


def test_audit_score_is_capped_when_operational_integrity_fails():
    score = audit_papers._score(
        {"safe": True},
        {"total": 1, "all_verified": True},
        {"exp": True},
        {"exp": {"output_hash_ok": True, "reproducible": True}},
        [],
        {"exp": {"ok": True}},
        {
            "ok": False,
            "unusable_output_blocks": [{"markers": ["zero molecular weight"]}],
            "contradictions": [],
        },
    )

    assert score <= 60


def test_math_prime_verification_does_not_emit_prime_gap_hypothesis():
    hypotheses = generate_hypothesis(
        "mathematics",
        [
            {
                "tool": "sympy_prime_analysis",
                "input": "is_prime:104729",
                "result": "104729 is prime: True",
                "success": True,
            }
        ],
    )

    joined = " ".join(h["hypothesis"].lower() for h in hypotheses)
    assert "prime gap distribution" not in joined
    assert all(h.get("novelty_status") != "candidate_novelty" for h in hypotheses)


def test_molecular_orbital_hypothesis_matches_homo_lumo_not_stoichiometry():
    hypotheses = generate_hypothesis(
        "chemistry",
        [
            {
                "tool": "molecular_orbital_energy",
                "input": "14",
                "result": "HOMO-LUMO gap: 1.045 eV\nDelocalization energy: -42.834 eV",
                "success": True,
            }
        ],
    )

    joined = " ".join(h["hypothesis"].lower() for h in hypotheses)
    assert "homo-lumo" in joined
    assert "stoichiometric" not in joined
    assert "reaction yields" not in joined


def test_quantum_rounded_rydberg_results_are_observations_not_novelty():
    hypotheses = generate_hypothesis(
        "physics",
        [
            {
                "tool": "quantum_energy_levels",
                "input": "hydrogen:50",
                "result": "Energy level n=50: -0.0054 eV",
                "success": True,
            }
        ],
    )

    assert all(h.get("novelty_status") != "candidate_novelty" for h in hypotheses)


def test_rydberg_scaling_comparison_gets_control_hypothesis():
    hypotheses = generate_hypothesis(
        "physics",
        [
            {
                "tool": "rydberg_scaling_comparison",
                "input": "1,2,3,5,10,20;delta=0.05",
                "result": (
                    "Hydrogen Rydberg scaling comparison:\n"
                    "inverse_square fit E = -13.600000*(1/n^2) + 0.000000; RMSE=0.000000 eV\n"
                    "Best model by RMSE: inverse_square"
                ),
                "success": True,
            }
        ],
    )

    assert hypotheses
    assert hypotheses[0]["novelty_status"] == "known_control"
    assert "inverse-square" in hypotheses[0]["hypothesis"]
    assert "RMSE" in hypotheses[0]["method"]


def test_conclusion_does_not_call_known_controls_novel():
    from communication.paper_enhancer import PaperEnhancer

    enhancer = PaperEnhancer()
    conclusion = enhancer._build_conclusion(
        "mathematics",
        "Prime Verification",
        [
            {
                "hypothesis": "The bounded verification reproduces known conjectural structures.",
                "confidence": 0.5,
                "method": "Increase bounds.",
                "novelty_status": "known_control",
            }
        ],
        [{"tool": "sympy_prime_analysis", "result": "104729 is prime: True"}],
    )

    assert "novel hypotheses" not in conclusion.lower()
    assert "known controls" in conclusion.lower() or "verification controls" in conclusion.lower()


def test_peer_review_novelty_does_not_reward_known_controls():
    review = PeerReviewer().review_paper(
        "mathematics",
        "Prime Verification",
        [{"tool": "sympy_prime_analysis", "result": "104729 is prime: True", "success": True}],
        [{"heading": "Discussion", "content": "A detailed discussion with enough words to avoid a discussion-depth penalty. " * 4}],
        [
            {
                "hypothesis": "Known primality verification control.",
                "confidence": 0.5,
                "method": "Repeat primality checks.",
                "novelty_status": "known_control",
            }
        ],
        ["Hardy, G.H. & Wright, E.M. (2008). An Introduction to the Theory of Numbers."],
        experiment_ids=[],
    )

    assert review["scores"]["novelty"] <= 4.0
    assert any("known" in item.lower() or "control" in item.lower() for item in review["feedback"])


def test_discussion_does_not_add_prime_gap_implication_without_gap_tool():
    enhancer = PaperEnhancer()
    discussion = enhancer._build_discussion(
        "mathematics",
        [
            {"tool": "sympy_prime_analysis", "description": "10000th prime", "result": "104729 is prime: True"},
            {"tool": "number_theory_advanced", "description": "Goldbach up to 1000", "result": "Goldbach verified for all even n <= 1000"},
        ],
        DOMAIN_INSIGHTS["mathematics"],
    )

    assert "Cramér" not in discussion
    assert "prime spacing" not in discussion


def test_discussion_prefers_exact_prime_gap_pattern_over_fuzzy_sympy_match():
    enhancer = PaperEnhancer()
    discussion = enhancer._build_discussion(
        "mathematics",
        [
            {
                "tool": "prime_gap_analysis",
                "description": "Prime gaps up to 1000",
                "result": "Prime gap analysis up to 1000:\nMean gap: 5.9581",
            }
        ],
        DOMAIN_INSIGHTS["mathematics"],
    )

    assert "distribution of prime gaps" in discussion.lower()
    assert "primality checks" not in discussion.lower()


def test_prime_gap_model_comparison_gets_conservative_hypothesis():
    hypotheses = generate_hypothesis(
        "mathematics",
        [
            {
                "tool": "prime_gap_model_comparison",
                "result": (
                    "Prime gap scaling model comparison:\n"
                    "max_gap_vs_logN_squared fit max_gap = 0.42*log(N)^2 + 1.0; RMSE=2.1"
                ),
            }
        ],
    )

    assert hypotheses
    assert hypotheses[0]["novelty_status"] == "finite_computational_observation"
    assert "log(N)^2" in hypotheses[0]["hypothesis"]
    assert "RMSE" in hypotheses[0]["method"]


def test_discussion_separates_prime_gap_model_comparison_from_gap_distribution():
    enhancer = PaperEnhancer()
    discussion = enhancer._build_discussion(
        "mathematics",
        [
            {
                "tool": "prime_gap_analysis",
                "description": "Prime gaps up to 1000",
                "result": "Prime gap analysis up to 1000:\nMean gap: 5.9581",
            },
            {
                "tool": "prime_gap_model_comparison",
                "description": "Logarithmic model comparison",
                "result": "Prime gap scaling model comparison:\nBest max-gap model by RMSE: logN_squared",
            },
        ],
        DOMAIN_INSIGHTS["mathematics"],
    )

    assert "distribution of prime gaps" in discussion.lower()
    assert "model-comparison control" in discussion.lower()
    assert "rmse" in discussion.lower()


def test_ungrounded_hypothesis_filter_drops_evolved_decimal_hallucinations():
    results = [
        {
            "tool": "prime_gap_model_comparison",
            "result": (
                "N=100000: mean_gap/logN=0.905530, max_gap/logN^2=0.543202\n"
                "N=1000000: mean_gap/logN=0.922087, max_gap/logN^2=0.597270\n"
                "RMSE=0.423559"
            ),
        }
    ]
    hypotheses = [
        {
            "hypothesis": "The supported trend uses max_gap/logN^2=0.543202.",
            "method": "Compare against RMSE=0.423559.",
            "confidence": 0.6,
        },
        {
            "hypothesis": "An evolved hypothesis claims a baseline of 0.780.",
            "method": "Expect ratios 1.13 and 1.11.",
            "confidence": 0.6,
        },
    ]

    kept = _filter_ungrounded_hypotheses(hypotheses, results)

    assert len(kept) == 1
    assert "0.543202" in kept[0]["hypothesis"]


def test_llm_discussion_sanitizer_removes_unsupported_decimal_sentences():
    results = [
        {
            "tool": "prime_gap_model_comparison",
            "result": (
                "mean_gap/logN=0.905530\n"
                "max_gap/logN^2=0.597270\n"
                "RMSE=0.015263"
            ),
        }
    ]
    content = (
        "The grounded ratio is 0.597270 and the RMSE is 0.015263. "
        "A speculative extrapolation predicts 0.67 at logN 16.1. "
        "The next test should extend the limit grid without treating that prediction as evidence."
    )

    cleaned, removed = _drop_unsupported_numeric_sentences(content, results)

    assert "0.597270" in cleaned
    assert "0.015263" in cleaned
    assert "0.67" not in cleaned
    assert "16.1" not in cleaned
    assert removed == ["0.67", "16.1"]


def test_math_branch_contract_adds_grounded_predictions_and_non_claims():
    discussion, hypotheses = _strengthen_branch_contract(
        "mathematics",
        "Existing discussion.",
        [
            {
                "hypothesis": f"Existing grounded hypothesis {i}",
                "method": "Testable via extending the recorded computation.",
                "confidence": 0.5,
                "novelty_status": "finite_computational_observation",
            }
            for i in range(3)
        ],
        [{"tool": "prime_gap_model_comparison", "result": "Best max-gap model by RMSE: logN_squared"}],
    )

    assert len(hypotheses) >= 5
    assert "does not claim" in discussion
    assert "verification control" in discussion
    assert "without asserting novelty" in discussion


def test_physics_branch_contract_adds_grounded_predictions_and_non_claims():
    discussion, hypotheses = _strengthen_branch_contract(
        "physics",
        "Existing discussion.",
        [
            {
                "hypothesis": f"Existing physics control {i}",
                "method": "Testable via repeating the recorded RMSE comparison.",
                "confidence": 0.5,
                "novelty_status": "known_control",
            }
            for i in range(2)
        ],
        [{"tool": "rydberg_scaling_comparison", "result": "Best model by RMSE: inverse_square"}],
    )

    assert len(hypotheses) >= 5
    assert "does not claim" in discussion
    assert "quantum-defect" in discussion
    assert "without asserting novelty" in discussion


def test_statistics_branch_contract_adds_grounded_predictions_and_non_claims():
    discussion, hypotheses = _strengthen_branch_contract(
        "statistics",
        "Existing discussion.",
        [
            {
                "hypothesis": "Existing statistics hypothesis with shared leading text " + str(i),
                "method": "Testable via adding observations under the same protocol.",
                "confidence": 0.5,
                "novelty_status": "finite_computational_observation",
            }
            for i in range(3)
        ],
        [{"tool": "two_sample_effect_power", "result": "95% CI for mean_difference"}],
    )

    assert len(hypotheses) >= 5
    assert len({h["hypothesis"][:80] for h in hypotheses}) >= 5
    assert "does not claim" in discussion
    assert "single-protocol" in discussion
    assert "without asserting novelty" in discussion


def test_biology_branch_contract_adds_grounded_predictions_and_non_claims():
    discussion, hypotheses = _strengthen_branch_contract(
        "biology",
        "Existing discussion.",
        [
            {
                "hypothesis": f"Existing biology hypothesis {i}",
                "method": "Testable via adding matched sequence panels.",
                "confidence": 0.5,
                "novelty_status": "finite_computational_observation",
            }
            for i in range(2)
        ],
        [{"tool": "gc_at_panel_comparison", "result": "95% CI for mean_gc_difference"}],
    )

    assert len(hypotheses) >= 5
    assert len({h["hypothesis"][:80] for h in hypotheses}) >= 5
    assert "does not claim" in discussion
    assert "taxonomic" in discussion
    assert "without asserting novelty" in discussion


def test_chemistry_ssh_branch_contract_adds_non_claims_and_statistical_scope():
    discussion, hypotheses = _strengthen_branch_contract(
        "chemistry",
        "Existing discussion.",
        [
            {
                "hypothesis": f"Existing chemistry hypothesis {i}",
                "method": "Testable via extending the recorded SSH grid.",
                "confidence": 0.5,
                "novelty_status": "finite_computational_observation",
            }
            for i in range(2)
        ],
        [
            {
                "tool": "ssh_polyene_gap_map",
                "result": (
                    "delta=0.025000; orientation=topological; "
                    "smallest_identifiable_n=4; edge_state_onset_n=60"
                ),
            }
        ],
    )

    assert len(hypotheses) >= 5
    assert len({h["hypothesis"][:80] for h in hypotheses}) >= 5
    assert "does not claim" in discussion
    assert "does not assert" in discussion
    assert "should not be treated" in discussion
    assert "calibration control" in discussion
    assert "verification control" in discussion
    assert "without asserting novelty" in discussion
    assert "p-value" in discussion
    assert "confidence interval" in discussion
    assert "effect size" in discussion
    assert "sample size" in discussion


def test_astronomy_branch_contract_adds_grounded_predictions_and_non_claims():
    discussion, hypotheses = _strengthen_branch_contract(
        "astronomy",
        "Existing discussion.",
        [
            {
                "hypothesis": f"Existing astronomy hypothesis {i}",
                "method": "Testable via extending the redshift grid.",
                "confidence": 0.5,
                "novelty_status": "finite_computational_observation",
            }
            for i in range(2)
        ],
        [{"tool": "cosmology_residual_comparison", "result": "max_abs_percent_residual"}],
    )

    assert len(hypotheses) >= 5
    assert len({h["hypothesis"][:80] for h in hypotheses}) >= 5
    assert "does not claim" in discussion
    assert "Hubble tension" in discussion
    assert "without asserting novelty" in discussion


def test_peer_review_reproducibility_uses_real_experiment_ids_without_rendered_data_section():
    _reset_tmp()
    exp_id = "test_audit_tmp"
    output = "tool output"
    (TMP_DIR / "output.txt").write_text(output, encoding="utf-8")
    (TMP_DIR / "provenance.json").write_text(
        json.dumps(
            {
                "experiment_id": exp_id,
                "tool": {
                    "name": "test_tool",
                    "input": "x",
                    "output_hash": hashlib.sha256(output.encode("utf-8")).hexdigest(),
                    "success": True,
                },
                "domain": "mathematics",
                "provenance_version": "1.0",
            }
        ),
        encoding="utf-8",
    )

    review = PeerReviewer().review_paper(
        "mathematics",
        "Reproducibility Gate",
        [{"tool": "test_tool", "result": "value = 1.23", "success": True}],
        [{"heading": "Methods", "content": "A method section before data availability rendering."}],
        [],
        ["Reference A", "Reference B", "Reference C"],
        experiment_ids=[exp_id],
    )

    assert review["scores"]["reproducibility"] == 9.0


def test_enhance_paper_builds_hypotheses_before_discussion():
    enhancer = PaperEnhancer()

    enhanced = asyncio.run(
        enhancer.enhance_paper(
            domain="mathematics",
            topic="Prime Gap Test",
            results=[
                {
                    "tool": "prime_gap_analysis",
                    "description": "Prime gaps up to 1000",
                    "result": "Prime gap analysis up to 1000:\nMean gap: 5.9581",
                    "success": True,
                }
            ],
            sections=[
                {"heading": "Introduction", "content": "Intro"},
                {"heading": "Methods", "content": "Methods"},
                {"heading": "Results", "content": "Results"},
                {"heading": "Discussion", "content": "Discussion"},
                {"heading": "Conclusion", "content": "Conclusion"},
            ],
            experiment_ids=[],
        )
    )

    assert enhanced["hypotheses"]
    discussion = next(s for s in enhanced["sections"] if s["heading"] == "Discussion")
    assert "prime gaps" in discussion["content"].lower()
    assert all("review" not in s["heading"].lower() for s in enhanced["sections"])
    assert enhanced["peer_review"]["overall_score"] >= 0


def test_enhancer_uses_astronomy_domain_instead_of_mathematics_fallback():
    enhancer = PaperEnhancer()

    enhanced = asyncio.run(
        enhancer.enhance_paper(
            domain="astronomy",
            topic="Stellar Physics",
            results=[
                {
                    "tool": "quantum_energy_levels",
                    "description": "Hydrogen n=2",
                    "result": "Hydrogen atom energy level n=2: E_2 = -3.4000 eV",
                    "success": True,
                },
                {
                    "tool": "numpy_correlation",
                    "description": "Temperature-luminosity correlation",
                    "result": "Pearson correlation coefficient: 0.951847",
                    "success": True,
                },
            ],
            sections=[
                {"heading": "Introduction", "content": "Intro"},
                {"heading": "Methods", "content": "Methods"},
                {"heading": "Results", "content": "Results"},
                {"heading": "Discussion", "content": "Discussion"},
                {"heading": "Conclusion", "content": "Conclusion"},
            ],
            experiment_ids=[],
        )
    )

    combined = " ".join(
        [enhanced["abstract"]]
        + [s["content"] for s in enhanced["sections"]]
        + enhanced["references"]
    ).lower()
    assert "mathematics research" not in combined
    assert "prime numbers" not in combined
    assert "stellar" in combined or "astrophysics" in combined


def test_prime_gap_detector_does_not_call_small_finite_cramer_gap_novel():
    result = prime_gap_novelty(
        [
            {
                "tool": "prime_gap_analysis",
                "input": "1000",
                "result": "Prime gaps up to 1000:\nMean gap: 5.95\nStd dev: 4.3\nMax gap: 20\nNumber of primes: 168",
                "success": True,
            },
            {
                "tool": "prime_gap_analysis",
                "input": "5000",
                "result": "Prime gaps up to 5000:\nMean gap: 7.85\nStd dev: 5.9\nMax gap: 34\nNumber of primes: 669",
                "success": True,
            },
            {
                "tool": "prime_gap_analysis",
                "input": "10000",
                "result": "Prime gaps up to 10000:\nMean gap: 8.80\nStd dev: 6.5\nMax gap: 36\nNumber of primes: 1229",
                "success": True,
            },
        ]
    )

    assert result["has_novelty"] is False
    assert result["novel_findings"] == []
    assert all(f.get("is_novel") is False for f in result["findings"])


def test_quantum_detector_treats_rounded_high_n_deviation_as_precision_control():
    result = quantum_scaling_novelty(
        [
            {"tool": "quantum_energy_levels", "input": "hydrogen:1", "result": "Energy level n=1: E_1 = -13.6000 eV", "success": True},
            {"tool": "quantum_energy_levels", "input": "hydrogen:10", "result": "Energy level n=10: E_10 = -0.1360 eV", "success": True},
            {"tool": "quantum_energy_levels", "input": "hydrogen:50", "result": "Energy level n=50: E_50 = -0.0054 eV", "success": True},
        ]
    )

    assert result["has_novelty"] is False
    assert result["novel_findings"] == []
    assert any(f.get("novelty_status") == "precision_artifact" for f in result["findings"])


def test_molecular_orbital_detector_reports_gap_fit_as_observation_or_candidate():
    result = molecular_orbital_novelty(
        [
            {"tool": "molecular_orbital_energy", "description": "4-carbon system", "result": "4-carbon system\nEnergies: [-1.0, -0.4, 0.4, 1.0]", "success": True},
            {"tool": "molecular_orbital_energy", "description": "6-carbon system", "result": "6-carbon system\nEnergies: [-1.2, -0.7, -0.2, 0.2, 0.7, 1.2]", "success": True},
            {"tool": "molecular_orbital_energy", "description": "8-carbon system", "result": "8-carbon system\nEnergies: [-1.4, -0.9, -0.5, -0.1, 0.1, 0.5, 0.9, 1.4]", "success": True},
        ]
    )

    assert result["has_novelty"] is False
    assert all(f.get("is_novel") is False for f in result["findings"])
    assert any(f.get("novelty_status") in {"finite_computational_observation", "candidate_novelty"} for f in result["findings"])


def test_learned_belief_confidence_changes_the_discussion_prompt():
    """The learning-ablation `weights` arm must have a REAL causal path.

    `_apply_weight_update` re-estimates belief confidences and the harness
    exports the mean via ``AMY_BELIEF_CONFIDENCE``. This guards that the LLM
    enhancer actually READS that signal and that low vs. high learned
    confidence produce materially different Discussion prompts — otherwise the
    `weights`/`both` arms would be causally identical to `none`/`feedback` and
    the ablation grid would report a phantom comparison.
    """
    import os
    from communication import llm_enhancer

    results = [{
        "tool": "prime_gap_analysis",
        "description": "Prime gap analysis up to 1000000",
        "result": "Number of primes: 78498. Largest gap: 114. Mean gap: 12.74",
        "experiment_id": "E1",
    }]

    class _CapturingClient:
        """Offline stand-in: records the prompt instead of calling a model."""
        def __init__(self):
            self.prompt = None

        async def chat(self, model, messages, temperature, max_tokens, **kwargs):
            # **kwargs absorbs think/num_ctx/format_json etc. so the mock stays
            # robust to the real OllamaCloudClient.chat signature evolving.
            self.prompt = messages[-1]["content"]
            return {"message": {"content": "x" * 200}}  # passes the >120 guard

    def _prompt_for(env_value=None, arg_value=None):
        os.environ.pop("AMY_BELIEF_CONFIDENCE", None)
        os.environ.pop("AMY_METAREVIEW_FEEDBACK", None)
        if env_value is not None:
            os.environ["AMY_BELIEF_CONFIDENCE"] = env_value
        client = _CapturingClient()
        try:
            asyncio.run(llm_enhancer.generate_discussion_llm(
                "mathematics", "Prime gaps", results, hypotheses=[],
                client=client, model="fake", belief_confidence=arg_value,
            ))
        finally:
            os.environ.pop("AMY_BELIEF_CONFIDENCE", None)
        return client.prompt

    baseline = _prompt_for(env_value=None)
    low = _prompt_for(env_value="0.20")
    high = _prompt_for(env_value="0.90")
    arg_wins = _prompt_for(env_value="0.20", arg_value=0.95)
    junk = _prompt_for(env_value="not-a-number")

    # Unset -> no calibration block (matches the `none`/`feedback` baseline).
    assert "Calibration:" not in baseline
    # The learned confidence is genuinely read and reaches the prompt.
    assert "Calibration:" in low and "0.20" in low and "LOW:" in low
    assert "Calibration:" in high and "0.90" in high and "HIGH:" in high
    # Low vs. high are materially different -> `weights` arm is not a no-op.
    assert low != high
    # Explicit arg wins over the env channel (mirrors the `feedback` param).
    assert "0.95" in arg_wins and "HIGH:" in arg_wins
    # A malformed signal degrades gracefully: no crash, no injection.
    assert "Calibration:" not in junk


def main():
    tests = [
        test_audit_recognizes_modern_provenance_paths_and_hashes,
        test_audit_rejects_mismatched_paper_cited_hash,
        test_audit_verifies_all_modern_provenance_hashes_not_just_first_two,
        test_paper_generator_cites_real_full_provenance_output_hash,
        test_paper_generator_rejects_publication_when_provenance_hash_is_missing,
        test_paper_generator_prepublication_gate_rejects_plain_unusable_output,
        test_audit_does_not_treat_sha256_chunks_as_experiment_ids,
        test_citation_verifier_strips_trailing_doi_punctuation,
        test_unknown_operation_output_is_not_scientific_evidence,
        test_zero_molecular_weight_output_is_not_scientific_evidence,
        test_provenance_manager_does_not_overwrite_same_second_tool_runs,
        test_audit_flags_zero_failure_claim_with_failed_tool_output,
        test_audit_flags_zero_molecular_weight_in_plain_result_text,
        test_audit_score_is_capped_when_operational_integrity_fails,
        test_math_prime_verification_does_not_emit_prime_gap_hypothesis,
        test_molecular_orbital_hypothesis_matches_homo_lumo_not_stoichiometry,
        test_quantum_rounded_rydberg_results_are_observations_not_novelty,
        test_conclusion_does_not_call_known_controls_novel,
        test_peer_review_novelty_does_not_reward_known_controls,
        test_discussion_does_not_add_prime_gap_implication_without_gap_tool,
        test_discussion_prefers_exact_prime_gap_pattern_over_fuzzy_sympy_match,
        test_peer_review_reproducibility_uses_real_experiment_ids_without_rendered_data_section,
        test_enhance_paper_builds_hypotheses_before_discussion,
        test_enhancer_uses_astronomy_domain_instead_of_mathematics_fallback,
        test_prime_gap_detector_does_not_call_small_finite_cramer_gap_novel,
        test_quantum_detector_treats_rounded_high_n_deviation_as_precision_control,
        test_molecular_orbital_detector_reports_gap_fit_as_observation_or_candidate,
        test_learned_belief_confidence_changes_the_discussion_prompt,
    ]
    try:
        for test in tests:
            test()
            print(f"PASS {test.__name__}")
    finally:
        shutil.rmtree(TMP_DIR, ignore_errors=True)
        TMP_PAPER.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
