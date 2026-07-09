from __future__ import annotations

import math

import numpy as np
import pytest

from atlas.app.ssh_disorder_benchmark import (
    BenchmarkConfig,
    build_realization,
    condition_seed,
    diagnostic_votes,
    exact_mcnemar_pvalue,
    format_benchmark_report,
    frontier_metrics,
    random_ssh_label,
    run_benchmark,
    wilson_interval,
)


def _config(**overrides) -> BenchmarkConfig:
    values = {
        "lengths": (20,),
        "deltas": (0.1,),
        "strengths": (0.2,),
        "disorder_types": ("off_diagonal",),
        "orientations": ("trivial", "topological"),
        "realizations": 4,
        "namespace": "paired-test",
    }
    values.update(overrides)
    return BenchmarkConfig(**values)


def test_condition_seed_pairs_orientations_but_separates_replicates():
    config = _config()

    trivial = condition_seed(
        config, "off_diagonal", 20, 0.1, 0.2, 3, "trivial"
    )
    topological = condition_seed(
        config, "off_diagonal", 20, 0.1, 0.2, 3, "topological"
    )
    next_replicate = condition_seed(
        config, "off_diagonal", 20, 0.1, 0.2, 4, "trivial"
    )

    assert trivial == topological
    assert trivial != next_replicate
    assert 0 <= trivial < 2**64


@pytest.mark.parametrize(
    ("hoppings", "expected"),
    [
        ([0.8, 1.2, 0.8, 1.2, 0.8], True),
        ([1.2, 0.8, 1.2, 0.8, 1.2], False),
    ],
)
def test_random_ssh_label_compares_log_geometric_means(hoppings, expected):
    assert random_ssh_label(hoppings) is expected


def test_diagnostic_votes_apply_frozen_two_of_three_rule():
    assert diagnostic_votes(
        gap_ratio=0.1,
        edge_weight=0.7,
        normalized_ipr=1.0,
        gap_threshold=0.2,
        edge_threshold=0.5,
        ipr_threshold=2.5,
    ) == {
        "gap": True,
        "edge": True,
        "ipr": False,
        "gap_only": True,
        "joint": True,
    }


@pytest.mark.parametrize(
    "overrides",
    [
        {"lengths": (19,)},
        {"deltas": (0.0,)},
        {"deltas": (1.0,)},
        {"strengths": (-0.1,)},
        {"disorder_types": ("unknown",)},
        {"orientations": ("left",)},
        {"realizations": 0},
        {"namespace": ""},
        {"edge_sites": 0},
        {"gap_threshold": -0.1},
        {"edge_threshold": 1.1},
        {"ipr_threshold": 0.0},
        {"protocol_sha256": "not-a-hash"},
    ],
)
def test_config_rejects_invalid_protocol_values(overrides):
    with pytest.raises(ValueError):
        _config(**overrides)


def _clean_hoppings(n: int, delta: float, orientation: str, beta=-2.5):
    strong = abs(beta) * (1.0 + delta)
    weak = abs(beta) * (1.0 - delta)
    starts_strong = orientation == "trivial"
    return np.array(
        [
            strong if ((index % 2 == 0) == starts_strong) else weak
            for index in range(n - 1)
        ],
        dtype=float,
    )


def test_zero_disorder_realization_matches_direct_clean_hamiltonian():
    config = _config(strengths=(0.0,))

    onsite, hoppings, seed = build_realization(
        config, "off_diagonal", 20, 0.1, 0.0, 0, "topological"
    )
    expected_hoppings = _clean_hoppings(20, 0.1, "topological")
    direct = np.diag(-expected_hoppings, 1) + np.diag(-expected_hoppings, -1)

    assert seed == condition_seed(
        config, "off_diagonal", 20, 0.1, 0.0, 0, "topological"
    )
    np.testing.assert_array_equal(onsite, np.zeros(20))
    np.testing.assert_allclose(hoppings, expected_hoppings, atol=0.0, rtol=0.0)
    metrics = frontier_metrics(onsite, hoppings, edge_sites=2)
    eigenvalues = np.linalg.eigvalsh(direct)
    expected_split = eigenvalues[10] - eigenvalues[9]
    assert metrics["frontier_splitting"] == pytest.approx(expected_split, abs=1e-12)


def test_off_diagonal_disorder_preserves_chiral_symmetry_and_pairs_noise():
    config = _config()
    trivial = build_realization(
        config, "off_diagonal", 20, 0.1, 0.2, 1, "trivial"
    )
    topological = build_realization(
        config, "off_diagonal", 20, 0.1, 0.2, 1, "topological"
    )

    np.testing.assert_array_equal(trivial[0], np.zeros(20))
    np.testing.assert_array_equal(topological[0], np.zeros(20))
    assert np.all(trivial[1] > 0.0)
    assert np.all(topological[1] > 0.0)
    np.testing.assert_allclose(
        trivial[1] / _clean_hoppings(20, 0.1, "trivial"),
        topological[1] / _clean_hoppings(20, 0.1, "topological"),
        atol=0.0,
        rtol=1e-15,
    )
    assert trivial[2] == topological[2]


def test_diagonal_disorder_retains_clean_hoppings_and_pairs_onsite_noise():
    config = _config(disorder_types=("diagonal",))
    trivial = build_realization(
        config, "diagonal", 20, 0.1, 0.2, 2, "trivial"
    )
    topological = build_realization(
        config, "diagonal", 20, 0.1, 0.2, 2, "topological"
    )

    np.testing.assert_array_equal(
        trivial[1], _clean_hoppings(20, 0.1, "trivial")
    )
    np.testing.assert_array_equal(
        topological[1], _clean_hoppings(20, 0.1, "topological")
    )
    np.testing.assert_array_equal(trivial[0], topological[0])
    assert np.any(trivial[0] != 0.0)


def test_frontier_metrics_detect_clean_topological_edge_localization():
    config = _config(lengths=(80,), strengths=(0.0,), deltas=(0.2,))
    onsite, hoppings, _ = build_realization(
        config, "off_diagonal", 80, 0.2, 0.0, 0, "topological"
    )

    metrics = frontier_metrics(onsite, hoppings, edge_sites=2)

    assert metrics["frontier_splitting"] < 1e-6
    assert metrics["edge_weight"] > 0.50
    assert metrics["ipr"] > 0.1
    assert metrics["normalized_ipr"] == pytest.approx(80 * metrics["ipr"])


@pytest.mark.parametrize(
    ("b", "c", "expected"),
    [
        (0, 0, 1.0),
        (0, 10, 2.0 / 2**10),
        (10, 0, 2.0 / 2**10),
        (3, 3, 1.0),
    ],
)
def test_exact_mcnemar_pvalue_uses_two_sided_binomial_tail(b, c, expected):
    assert exact_mcnemar_pvalue(b, c) == pytest.approx(expected)


@pytest.mark.parametrize(("successes", "total"), [(0, 10), (5, 10), (10, 10)])
def test_wilson_interval_is_bounded_and_contains_observed_rate(successes, total):
    low, high = wilson_interval(successes, total)
    observed = successes / total

    assert 0.0 <= low <= observed <= high <= 1.0


def test_small_benchmark_is_deterministic_and_separates_negative_control():
    config = BenchmarkConfig(
        lengths=(20,),
        deltas=(0.1,),
        strengths=(0.0, 0.2),
        disorder_types=("off_diagonal", "diagonal"),
        orientations=("trivial", "topological"),
        realizations=8,
        namespace="small-deterministic-study",
        protocol_sha256="a" * 64,
    )

    first = run_benchmark(config)
    second = run_benchmark(config)

    assert first == second
    assert first["protocol_sha256"] != "a" * 64
    assert first["preregistration_sha256"] == "a" * 64
    assert len(first["records"]) == 36
    assert len(first["summaries"]) == 4
    assert first["pooled"]["total"] == 18
    assert 0.0 <= first["pooled"]["mcnemar_pvalue"] <= 1.0
    assert len(first["pooled"]["error_difference_ci95"]) == 2
    off_diagonal = [
        row for row in first["summaries"]
        if row["disorder_type"] == "off_diagonal"
    ]
    diagonal = [
        row for row in first["summaries"]
        if row["disorder_type"] == "diagonal"
    ]
    assert all(row["gap_accuracy"] is not None for row in off_diagonal)
    assert all(row["joint_accuracy"] is not None for row in off_diagonal)
    assert all(row["gap_accuracy"] is None for row in diagonal)
    assert all(row["joint_accuracy"] is None for row in diagonal)
    assert all(record["reference_label"] is None for record in first["records"] if record["disorder_type"] == "diagonal")
    assert all(
        math.isfinite(record["frontier_splitting"])
        for record in first["records"]
    )

    report = format_benchmark_report(first)
    assert "SSH disorder diagnostic benchmark" in report
    assert "primary_estimand=error_gap_minus_error_joint" in report
    assert "reference_label=not_defined" in report
