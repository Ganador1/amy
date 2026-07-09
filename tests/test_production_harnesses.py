from __future__ import annotations

import configparser
import py_compile
import sys
from collections import deque
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent


def test_e2e_validation_script_compiles():
    py_compile.compile(
        str(ROOT / "scripts" / "run" / "run_e2e_validation.py"),
        doraise=True,
    )


def test_e2e_domain_plans_start_with_diverse_valid_calls():
    from scripts.run.run_e2e_validation import DOMAIN_PLANS

    for domain, plan in DOMAIN_PLANS.items():
        first_three = plan["calls"][:3]
        assert len(first_three) >= 2, domain
        assert len({tool for tool, _, _ in first_three}) >= 2, domain


def test_e2e_physics_plan_uses_quantum_tool_protocol():
    from scripts.run.run_e2e_validation import DOMAIN_PLANS

    quantum_calls = [
        tool_input
        for tool, tool_input, _ in DOMAIN_PLANS["physics"]["calls"]
        if tool == "quantum_energy_levels"
    ]

    assert quantum_calls
    assert all(call.startswith("hydrogen:") for call in quantum_calls)


def test_e2e_physics_plan_uses_rydberg_scaling_comparison():
    from scripts.run.run_e2e_validation import DOMAIN_PLANS

    calls = DOMAIN_PLANS["physics"]["calls"]
    scaling_calls = [
        tool_input
        for tool, tool_input, _ in calls
        if tool == "rydberg_scaling_comparison"
    ]

    assert scaling_calls
    counts = [int(part) for part in scaling_calls[0].split(";", 1)[0].split(",")]
    assert counts[:3] == [1, 2, 3]
    assert counts[-1] >= 20
    assert "delta=" in scaling_calls[0]


def test_e2e_math_plan_uses_sympy_prime_protocol():
    from scripts.run.run_e2e_validation import DOMAIN_PLANS

    valid_operations = {"is_prime", "nth_prime", "prime_range", "prime_count"}
    sympy_calls = [
        tool_input
        for tool, tool_input, _ in DOMAIN_PLANS["mathematics"]["calls"]
        if tool == "sympy_prime_analysis"
    ]

    assert sympy_calls
    assert all(":" in call for call in sympy_calls)
    assert all(call.split(":", 1)[0] in valid_operations for call in sympy_calls)


def test_e2e_math_plan_uses_prime_gap_model_comparison():
    from scripts.run.run_e2e_validation import DOMAIN_PLANS

    calls = DOMAIN_PLANS["mathematics"]["calls"]
    model_calls = [
        tool_input
        for tool, tool_input, _ in calls
        if tool == "prime_gap_model_comparison"
    ]

    assert model_calls
    limits = [int(part) for part in model_calls[0].split(",")]
    assert limits == sorted(limits)
    assert len(limits) >= 3
    assert limits[-1] >= 1_000_000


def test_e2e_statistics_plan_uses_effect_power_control():
    from scripts.run.run_e2e_validation import DOMAIN_PLANS

    calls = DOMAIN_PLANS["statistics"]["calls"]
    effect_calls = [
        tool_input
        for tool, tool_input, _ in calls
        if tool == "two_sample_effect_power"
    ]

    assert effect_calls
    assert effect_calls[0].count("[") >= 2
    assert ";" in effect_calls[0] or ":" in effect_calls[0]


def test_e2e_astronomy_plan_uses_cosmology_residual_control():
    from scripts.run.run_e2e_validation import DOMAIN_PLANS

    calls = DOMAIN_PLANS["astronomy"]["calls"]
    residual_calls = [
        tool_input
        for tool, tool_input, _ in calls
        if tool == "cosmology_residual_comparison"
    ]

    assert residual_calls
    assert residual_calls[0].split(";", 1)[0].startswith("0.01,0.1")
    assert "threshold=" in residual_calls[0]
    assert any(tool == "astropy_cosmology" for tool, _, _ in calls)


def test_e2e_biology_plan_uses_gc_at_panel_control():
    from scripts.run.run_e2e_validation import DOMAIN_PLANS

    calls = DOMAIN_PLANS["biology"]["calls"]
    panel_calls = [
        tool_input
        for tool, tool_input, _ in calls
        if tool == "gc_at_panel_comparison"
    ]

    assert panel_calls
    assert "gc=" in panel_calls[0]
    assert "at=" in panel_calls[0]
    assert ";" in panel_calls[0]
    assert any(tool == "dnabert2_analysis" for tool, _, _ in calls)


def test_e2e_chemistry_plan_targets_polyene_scaling():
    from scripts.run.run_e2e_validation import DOMAIN_PLANS

    calls = DOMAIN_PLANS["chemistry"]["calls"]
    assert DOMAIN_PLANS["chemistry"]["topic"] == (
        "SSH polyene finite-chain identifiability: Peierls gaps versus edge-state contamination"
    )
    assert any(tool == "ssh_polyene_gap_map" for tool, _, _ in calls)
    assert any(tool == "ssh_edge_localization_map" for tool, _, _ in calls)

    ssh_calls = [
        tool_input
        for tool, tool_input, _ in calls
        if tool == "ssh_polyene_gap_map"
    ]
    assert ssh_calls
    assert "deltas=" in ssh_calls[0]
    assert "orientations=trivial,topological" in ssh_calls[0]
    assert "threshold=0.05" in ssh_calls[0]

    localization_calls = [
        tool_input
        for tool, tool_input, _ in calls
        if tool == "ssh_edge_localization_map"
    ]
    assert localization_calls
    assert "edge_sites=2" in localization_calls[0]
    assert "localization_threshold=0.25" in localization_calls[0]

    scaling_calls = [
        tool_input
        for tool, tool_input, _ in calls
        if tool == "huckel_polyene_scaling"
    ]

    assert scaling_calls
    chain_sizes = [int(part) for part in scaling_calls[0].split(",")]
    assert chain_sizes[:3] == [4, 6, 8]
    assert len(chain_sizes) >= 7
    assert chain_sizes[-1] >= 100
    assert any(tool == "bond_alternated_polyene_scaling" for tool, _, _ in calls)
    assert any(tool == "pyscf_polyene_hf_gap" for tool, _, _ in calls)


def test_e2e_chemistry_plan_includes_preregistered_disorder_replication():
    from scripts.run.run_e2e_validation import DOMAIN_PLANS

    calls = [
        tool_input
        for tool, tool_input, _ in DOMAIN_PLANS["chemistry"]["calls"]
        if tool == "ssh_disorder_diagnostic_benchmark"
    ]

    assert len(calls) == 2
    assert any("namespace=amy-ssh-disorder-v1-primary" in call for call in calls)
    assert any(
        "namespace=amy-ssh-disorder-v1-replication" in call for call in calls
    )
    for call in calls:
        assert "20,40,80" in call
        assert "deltas=0.05,0.1,0.2" in call
        assert "strengths=0,0.05,0.1,0.2,0.4" in call
        assert "disorders=off_diagonal,diagonal" in call
        assert "orientations=trivial,topological" in call
        assert "realizations=128" in call


def test_extended_polyene_geometry_builder_counts_atoms():
    sys.path.insert(0, str(ROOT / "atlas"))
    from app.extended_science_tools import _polyene_atom_string

    c4 = _polyene_atom_string(4)
    c6 = _polyene_atom_string(6)

    assert sum(1 for atom in c4.split("; ") if atom.startswith("C ")) == 4
    assert sum(1 for atom in c4.split("; ") if atom.startswith("H ")) == 6
    assert sum(1 for atom in c6.split("; ") if atom.startswith("C ")) == 6
    assert sum(1 for atom in c6.split("; ") if atom.startswith("H ")) == 8


def test_e2e_sections_format_tool_inputs_for_auditing():
    from scripts.run.run_e2e_validation import _build_sections

    sections = _build_sections(
        "chemistry",
        "Huckel scaling",
        [
            {
                "description": "Scaling run",
                "tool": "huckel_polyene_scaling",
                "input": "4,6,8",
                "experiment_id": "chemistry_huckel_polyene_scaling_20260702_010203",
                "result": "result",
            }
        ],
    )

    results = next(section for section in sections if section["heading"] == "Results")
    assert "**Tool:** `huckel_polyene_scaling`" in results["content"]
    assert "**Input:** `4,6,8`" in results["content"]


def test_e2e_sections_keep_late_statistical_markers_for_long_results():
    from scripts.run.run_e2e_validation import _build_sections

    long_result = (
        "Hydrogen Rydberg scaling comparison:\n"
        + ("  n=1: residual=0.000000 eV\n" * 45)
        + "  Deterministic residual statistics: sample size n=6; "
        "residual standard deviation=0.000000 eV; effect size=0.604522 eV; "
        "confidence interval: not estimated\n"
    )

    sections = _build_sections(
        "physics",
        "Rydberg scaling",
        [
            {
                "description": "Rydberg scaling",
                "tool": "rydberg_scaling_comparison",
                "input": "1,2,3,5,10,20;delta=0.05",
                "experiment_id": "physics_rydberg_scaling_comparison_20260703_010203",
                "result": long_result,
            }
        ],
    )

    results = next(section for section in sections if section["heading"] == "Results")
    assert "sample size n=6" in results["content"]
    assert "confidence interval: not estimated" in results["content"]


def test_llm_evidence_context_keeps_huckel_fit_metrics():
    from communication.llm_enhancer import _format_results_context

    long_result = (
        "Hückel polyene HOMO-LUMO gap scaling:\n"
        + ("  n=4: gap=3.090170 eV\n" * 30)
        + "  inverse_linear fit gap = 15.481724/(n+1) + 0.008151; RMSE=0.006472 eV; R2=0.999945\n"
        + "  inverse_quadratic fit gap = 73.461186/(n+1)^2 + 0.493610; RMSE=0.256926 eV; R2=0.912976\n"
    )

    context = _format_results_context(
        [{"tool": "huckel_polyene_scaling", "result": long_result}]
    )

    assert "inverse_linear fit gap" in context
    assert "inverse_quadratic fit gap" in context


def test_live_probe_extracts_new_results_from_bounded_deque():
    from scripts.diagnostics import live_amy_probe

    history = deque(
        [
            {"tool_name": "old_tool", "result": "old"},
            {"tool_name": "new_tool", "result": "new"},
        ],
        maxlen=20,
    )

    assert live_amy_probe._new_tool_results(history, 1) == [
        {"tool_name": "new_tool", "result": "new"}
    ]


def test_live_probe_handles_deque_eviction_when_history_wraps():
    from scripts.diagnostics import live_amy_probe

    history = deque([{"tool_name": f"tool_{i}"} for i in range(20)], maxlen=20)

    assert live_amy_probe._new_tool_results(history, 25) == []


def test_pytest_default_collection_is_limited_to_project_tests():
    parser = configparser.ConfigParser()
    parser.read(ROOT / "pytest.ini")

    assert parser.get("pytest", "testpaths") == "tests"
