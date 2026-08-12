from experiments.unit_distance_search.search import (
    best_square_grid_baseline,
    canonical_displacements,
    count_unit_edges,
    evolve_configuration,
    greedy_configuration,
    square_grid,
    verify_configuration,
)


def test_displacements_are_canonical_and_exact():
    assert canonical_displacements(1) == ((0, 1), (1, 0))
    assert canonical_displacements(5) == ((1, -2), (1, 2), (2, -1), (2, 1))
    assert canonical_displacements(3) == ()


def test_square_grid_edge_counts_match_closed_controls():
    points = square_grid(4)
    assert count_unit_edges(points, 1) == 24
    assert count_unit_edges(points, 5) == 24
    assert verify_configuration(list(points), 1, 24).valid is True


def test_independent_verifier_rejects_duplicates_and_wrong_claim():
    duplicate = verify_configuration([(0, 0), (0, 0)], 1)
    assert duplicate.valid is False
    wrong_count = verify_configuration([(0, 0), (1, 0)], 1, claimed_edges=2)
    assert wrong_count.valid is False
    assert wrong_count.edge_count == 1


def test_independent_verifier_accepts_json_point_lists():
    result = verify_configuration([[0, 0], [1, 0], [0, 1]], 1, claimed_edges=2)
    assert result.valid is True
    assert result.edge_count == 2


def test_baseline_exhausts_radius_range():
    baseline = best_square_grid_baseline(side=6, max_squared_distance=50)
    assert baseline["squared_distance"] == 5
    assert baseline["edges"] == 80


def test_seeded_evolution_is_reproducible_and_never_loses_best():
    initial = greedy_configuration(36, 5)
    initial_edges = count_unit_edges(initial, 5)
    first = evolve_configuration(initial, 5, steps=500, seed=17)
    second = evolve_configuration(initial, 5, steps=500, seed=17)
    assert first == second
    assert first["edges"] >= initial_edges
    assert verify_configuration(list(first["points"]), 5, first["edges"]).valid is True
