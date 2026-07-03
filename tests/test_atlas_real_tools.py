"""Deterministic tests for core.atlas_real_tools.

Every test exercises a tool with a *known* answer (either an analytic
identity, a value from the literature, or a property that the function
must preserve). We never assert on a value pulled out of the same dict
the tool reads — that would just test that the dict can be read.

Run with:
    .venv/bin/python -m pytest tests/test_atlas_real_tools.py -q
"""
from __future__ import annotations

import math

import pytest

from core.atlas_real_tools import (
    automated_prover_induction_sum_first_n_powers,
    automated_prover_irrational_root,
    collatz_sequence,
    correlation_analysis,
    correlation_analysis_from_query,
    deterministic_bootstrap_mean_difference_ci,
    deterministic_sample,
    dnabert2_batch_analysis,
    dnabert2_motifs,
    euler_characteristic_from_face_vector,
    euler_characteristic_named_space,
    goldbach_decomposition,
    graph_chromatic_number,
    graph_eulerian,
)


# ─── DNABERT2 motifs ──────────────────────────────────────────────────────────


class TestDnabert2Motifs:
    def test_detects_minus_10_box(self):
        seq = "AAAAATATAATAAAAA"  # contains TATAAT
        out = dnabert2_motifs(seq)
        assert "TATAAT" in out
        assert "−10 box" in out

    def test_rejects_invalid_bases(self):
        out = dnabert2_motifs("ATCGZ")
        assert out.startswith("Error:")
        assert "Z" in out

    def test_rejects_empty(self):
        out = dnabert2_motifs("")
        assert out.startswith("Error:")

    def test_gc_content_correct(self):
        # 4 G/C out of 8 → 50%
        out = dnabert2_motifs("ATATGCGC")
        assert "GC content: 50.0%" in out

    def test_is_deterministic(self):
        # Same input must produce IDENTICAL output. This is the regression
        # test against the random.random() / np.random injection that the
        # old code had.
        seq = "CAATAAATATAATAAAAATTGACAAAAACAAT"
        out1 = dnabert2_motifs(seq)
        out2 = dnabert2_motifs(seq)
        assert out1 == out2

    def test_sigma70_promoter_call(self):
        # Promoter with both -35 (TTGACA) and -10 (TATAAT)
        seq = "AAATTGACAAAAAAAAAAAAATATAATAAAA"
        out = dnabert2_motifs(seq)
        assert "σ70" in out or "prokaryotic promoter" in out

    def test_tm_short_oligo_wallace(self):
        # Wallace rule for n<14: Tm = 2*(A+T)+4*(G+C)
        # "ATGC" → 2*2 + 4*2 = 12
        out = dnabert2_motifs("ATGC")
        assert "12.0 °C" in out


# ─── DNABERT2 batch ───────────────────────────────────────────────────────────


class TestDnabert2Batch:
    def test_empty_batch_errors(self):
        assert dnabert2_batch_analysis([]).startswith("Error:")

    def test_all_invalid_rejected(self):
        out = dnabert2_batch_analysis(["XYZ", "QQQQ"])
        assert out.startswith("Error:")

    def test_counts_accepted_and_rejected(self):
        out = dnabert2_batch_analysis(["ATCG", "INVALID!", "GGCC"])
        assert "accepted: 2" in out
        assert "rejected: 1" in out

    def test_gc_aggregate(self):
        # All-AT and all-GC ⇒ mean GC = 50%
        out = dnabert2_batch_analysis(["AAAATTTT", "GGGGCCCC"])
        assert "mean=50.00%" in out

    def test_motif_sensitivity_deterministic(self):
        seqs = ["TATAAT" + "A" * 20, "AAAA" + "TATAAT" + "AAAA", "GGGGGG"]
        out1 = dnabert2_batch_analysis(seqs)
        out2 = dnabert2_batch_analysis(seqs)
        assert out1 == out2
        # 2/3 sequences contain TATAAT
        assert "TATAAT: 0.667" in out1


# ─── Correlation analysis ─────────────────────────────────────────────────────


class TestCorrelation:
    def test_perfect_positive_correlation(self):
        out = correlation_analysis([1, 2, 3, 4, 5], [2, 4, 6, 8, 10])
        assert "Pearson r  = +1.000000" in out
        assert "Spearman ρ = +1.000000" in out

    def test_perfect_negative_correlation(self):
        out = correlation_analysis([1, 2, 3, 4, 5], [5, 4, 3, 2, 1])
        assert "Pearson r  = -1.000000" in out

    def test_zero_correlation_uncorrelated_input(self):
        # x and y constructed orthogonal-ish: Σxy = 0 after centering.
        x = [-2, -1, 0, 1, 2]
        y = [4, 1, 0, 1, 4]  # y = x^2 — Pearson r is 0 because x is symmetric
        out = correlation_analysis(x, y)
        # Pearson r should be ~ 0 here (symmetric quadratic, odd in x mean=0)
        assert "Pearson r  = +0.000000" in out or "Pearson r  = -0.000000" in out

    def test_unequal_lengths_error(self):
        out = correlation_analysis([1, 2, 3], [1, 2])
        assert out.startswith("Error:")

    def test_n_too_small_error(self):
        out = correlation_analysis([1, 2], [3, 4])
        assert out.startswith("Error:")
        assert "n>=3" in out or "n=2" in out

    def test_zero_variance_error(self):
        out = correlation_analysis([1, 1, 1, 1], [1, 2, 3, 4])
        assert out.startswith("Error:")
        assert "zero variance" in out

    def test_deterministic_no_hidden_state(self):
        out1 = correlation_analysis([1, 2, 3, 4, 5, 6, 7], [1.1, 2.0, 3.1, 4.2, 4.9, 6.1, 7.0])
        out2 = correlation_analysis([1, 2, 3, 4, 5, 6, 7], [1.1, 2.0, 3.1, 4.2, 4.9, 6.1, 7.0])
        assert out1 == out2

    def test_query_parser_semicolon(self):
        out = correlation_analysis_from_query("[1,2,3,4,5];[2,4,6,8,10]")
        assert "Pearson r  = +1.000000" in out

    def test_query_parser_correlation_prefix(self):
        out = correlation_analysis_from_query("correlation:[1,2,3],[4,5,6]")
        assert "Pearson r" in out


# ─── Automated prover ─────────────────────────────────────────────────────────


class TestAutomatedProver:
    def test_sum_first_n_p1_classic_formula(self):
        out = automated_prover_induction_sum_first_n_powers(1, n_max=5)
        assert "all checks pass: True" in out
        # The closed form should appear (sympy returns n*(n+1)/2 form)
        assert "n" in out

    def test_sum_first_n_p2_classic_formula(self):
        # Σ k^2 from 1..5 = 55
        out = automated_prover_induction_sum_first_n_powers(2, n_max=5)
        assert "n=5: LHS=55, RHS=55" in out
        assert "all checks pass: True" in out

    def test_sum_first_n_p3_classic_formula(self):
        # Σ k^3 from 1..4 = (4*5/2)^2 = 100
        out = automated_prover_induction_sum_first_n_powers(3, n_max=4)
        assert "n=4: LHS=100, RHS=100" in out

    def test_sum_unsupported_p(self):
        out = automated_prover_induction_sum_first_n_powers(7)
        assert out.startswith("Error:")

    def test_irrational_root_2(self):
        out = automated_prover_irrational_root(2)
        assert "irrational" in out
        assert "2: 1" in out  # factorization {2: 1}

    def test_irrational_root_perfect_square(self):
        out = automated_prover_irrational_root(9)
        assert "rational" in out
        assert "= 3" in out

    def test_irrational_root_large_composite(self):
        out = automated_prover_irrational_root(72)  # 2^3 * 3^2 → odd exponent → irrational
        assert "irrational" in out

    def test_irrational_root_invalid(self):
        out = automated_prover_irrational_root(0)
        assert out.startswith("Error:")


# ─── Graph theory ─────────────────────────────────────────────────────────────


class TestGraphTheory:
    def test_complete_graph_chromatic(self):
        # χ(K_n) = n
        out = graph_chromatic_number("complete:5")
        assert "exact χ" in out and ": 5" in out

    def test_cycle_even_chromatic(self):
        # χ(C_{2k}) = 2
        out = graph_chromatic_number("cycle:6")
        assert "exact χ" in out and ": 2" in out

    def test_cycle_odd_chromatic(self):
        # χ(C_{2k+1}) = 3
        out = graph_chromatic_number("cycle:5")
        assert "exact χ" in out and ": 3" in out

    def test_path_chromatic(self):
        # χ(P_n) = 2 for n>=2, 1 for n=1
        out = graph_chromatic_number("path:5")
        assert "exact χ" in out and ": 2" in out

    def test_petersen_chromatic(self):
        # Petersen graph has χ = 3
        out = graph_chromatic_number("petersen")
        assert "exact χ" in out and ": 3" in out

    def test_bipartite_chromatic(self):
        # K_{3,4} bipartite ⇒ χ = 2
        out = graph_chromatic_number("bipartite:3,4")
        assert "bipartite? True" in out
        assert "exact χ" in out and ": 2" in out

    def test_arbitrary_edge_list(self):
        # Triangle K_3 via edge list ⇒ χ = 3
        out = graph_chromatic_number("edges:1-2,2-3,1-3")
        assert "exact χ" in out and ": 3" in out

    def test_invalid_spec(self):
        out = graph_chromatic_number("nonsense")
        assert out.startswith("Error:")

    def test_eulerian_cycle_even(self):
        # C_n always has all-even degrees ⇒ Eulerian circuit
        out = graph_eulerian("cycle:6")
        assert "Eulerian circuit" in out

    def test_eulerian_path_K4(self):
        # K_4: all vertices degree 3 (odd, four odd vertices) ⇒ no Eulerian
        out = graph_eulerian("complete:4")
        assert "no Eulerian" in out

    def test_eulerian_path_with_two_odd(self):
        # Path graph P_n for n>=2 has exactly 2 odd-degree vertices ⇒ Eulerian path
        out = graph_eulerian("path:5")
        assert "Eulerian path" in out


# ─── Topology invariants ──────────────────────────────────────────────────────


class TestTopology:
    def test_euler_from_fvector_sphere(self):
        # Tetrahedron boundary: f = (4, 6, 4) ⇒ χ = 4-6+4 = 2
        out = euler_characteristic_from_face_vector([4, 6, 4])
        assert "χ = 2" in out

    def test_euler_from_fvector_torus(self):
        # Minimal triangulation T^2: (7, 21, 14) ⇒ χ = 0
        out = euler_characteristic_from_face_vector([7, 21, 14])
        assert "χ = 0" in out

    def test_euler_named_sphere(self):
        out = euler_characteristic_named_space("sphere")
        assert "χ = 2" in out

    def test_euler_named_torus(self):
        out = euler_characteristic_named_space("torus")
        assert "χ = 0" in out

    def test_euler_named_klein_bottle(self):
        out = euler_characteristic_named_space("klein_bottle")
        assert "χ = 0" in out

    def test_euler_named_rp2(self):
        out = euler_characteristic_named_space("rp2")
        assert "χ = 1" in out

    def test_euler_named_circle(self):
        out = euler_characteristic_named_space("circle")
        assert "χ = 0" in out

    def test_euler_invalid_fv(self):
        out = euler_characteristic_from_face_vector([])
        assert out.startswith("Error:")

    def test_euler_negative_fv(self):
        out = euler_characteristic_from_face_vector([4, -1, 4])
        assert out.startswith("Error:")

    def test_euler_unknown_space(self):
        out = euler_characteristic_named_space("xyzzy")
        assert out.startswith("Error:")


# ─── Conjecture evaluators ────────────────────────────────────────────────────


class TestConjectures:
    def test_collatz_small_n(self):
        # n=27 is a classic "long" Collatz: 111 steps to reach 1
        out = collatz_sequence(27)
        assert "reached 1: True" in out
        assert "steps: 111" in out

    def test_collatz_power_of_2(self):
        # n=64 reaches 1 in exactly 6 steps (64→32→16→8→4→2→1)
        out = collatz_sequence(64)
        assert "steps: 6" in out

    def test_collatz_one(self):
        out = collatz_sequence(1)
        assert "steps: 0" in out

    def test_collatz_invalid(self):
        out = collatz_sequence(0)
        assert out.startswith("Error:")

    def test_goldbach_small_even(self):
        # n=10: pairs (3,7), (5,5) → 2 decompositions
        out = goldbach_decomposition(10)
        assert "decompositions found: 2" in out
        assert "(3, 7)" in out
        assert "(5, 5)" in out

    def test_goldbach_invalid_odd(self):
        out = goldbach_decomposition(9)
        assert out.startswith("Error:")

    def test_goldbach_invalid_too_small(self):
        out = goldbach_decomposition(2)
        assert out.startswith("Error:")


# ─── Deterministic sampling ───────────────────────────────────────────────────


class TestDeterministicSample:
    def test_same_seed_same_output(self):
        a = deterministic_sample("normal", 100, 0.0, 1.0, seed=42)
        b = deterministic_sample("normal", 100, 0.0, 1.0, seed=42)
        assert a == b  # identical, even though the underlying numbers are random

    def test_different_seed_different_output(self):
        a = deterministic_sample("normal", 100, 0.0, 1.0, seed=42)
        b = deterministic_sample("normal", 100, 0.0, 1.0, seed=43)
        assert a != b

    def test_uniform_in_bounds(self):
        out = deterministic_sample("uniform", 1000, -1.0, 1.0, seed=0)
        # min/max should be within [-1, 1]
        for line in out.splitlines():
            if line.strip().startswith("min ="):
                v = float(line.split("=")[1].strip())
                assert v >= -1.0
            if line.strip().startswith("max ="):
                v = float(line.split("=")[1].strip())
                assert v <= 1.0

    def test_normal_sample_stats(self):
        # n=10000 normal(0,1): mean and std should be near 0 and 1
        out = deterministic_sample("normal", 10000, 0.0, 1.0, seed=7)
        for line in out.splitlines():
            if line.strip().startswith("mean="):
                m = float(line.split("=")[1].strip())
                assert abs(m) < 0.1  # within 0.1 of 0
            if line.strip().startswith("std ="):
                s = float(line.split("=")[1].strip())
                assert abs(s - 1.0) < 0.1

    def test_poisson_lambda(self):
        # Sample mean ≈ λ for n large
        out = deterministic_sample("poisson", 10000, 5.0, seed=11)
        for line in out.splitlines():
            if line.strip().startswith("mean="):
                m = float(line.split("=")[1].strip())
                assert abs(m - 5.0) < 0.15

    def test_invalid_dist(self):
        out = deterministic_sample("cauchy", 10, 0.0, 1.0, seed=0)
        assert out.startswith("Error:")

    def test_invalid_n(self):
        out = deterministic_sample("normal", 0, 0.0, 1.0, seed=0)
        assert out.startswith("Error:")

    def test_normal_std_must_be_positive(self):
        out = deterministic_sample("normal", 100, 0.0, -1.0, seed=0)
        assert out.startswith("Error:")

    def test_bootstrap_mean_difference_ci_is_seeded(self):
        a = deterministic_bootstrap_mean_difference_ci(
            [1.0, 2.0, 3.0, 4.0],
            [2.0, 3.0, 4.0, 5.0],
            seed=123,
            iterations=250,
        )
        b = deterministic_bootstrap_mean_difference_ci(
            [1.0, 2.0, 3.0, 4.0],
            [2.0, 3.0, 4.0, 5.0],
            seed=123,
            iterations=250,
        )
        assert a == b
        assert a[0] <= 1.0 <= a[1]


# ─── Anti-regression: NO module-level non-determinism ─────────────────────────


class TestNoNonDeterminism:
    """Catch any future regression that re-introduces random.* in tool outputs."""

    @pytest.mark.parametrize(
        "call",
        [
            lambda: dnabert2_motifs("ATATGCGCATATATGCGCTATAATAATA"),
            lambda: dnabert2_batch_analysis(["ATCG", "GGCC", "AAAA"]),
            lambda: correlation_analysis([1, 2, 3, 4, 5], [1, 3, 2, 5, 4]),
            lambda: automated_prover_induction_sum_first_n_powers(2, n_max=4),
            lambda: automated_prover_irrational_root(7),
            lambda: graph_chromatic_number("petersen"),
            lambda: graph_eulerian("cycle:8"),
            lambda: euler_characteristic_named_space("klein_bottle"),
            lambda: collatz_sequence(27),
            lambda: goldbach_decomposition(100),
        ],
    )
    def test_call_is_deterministic(self, call):
        a = call()
        b = call()
        c = call()
        assert a == b == c, "Tool emitted different outputs on repeat — suspect random.*"
