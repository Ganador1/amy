"""Deterministic finite searches for planar point sets with many unit distances.

Integer lattice points are scaled by ``1 / sqrt(squared_distance)``.  This
lets the verifier decide whether a pair is at unit distance with exact integer
arithmetic, avoiding floating-point tolerance choices.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass


Point = tuple[int, int]


@dataclass(frozen=True)
class Verification:
    valid: bool
    point_count: int
    edge_count: int
    squared_distance: int
    reason: str


def canonical_displacements(squared_distance: int) -> tuple[Point, ...]:
    """Return one vector from each undirected integer vector pair of a length."""
    if squared_distance <= 0:
        return ()
    radius = math.isqrt(squared_distance)
    vectors = []
    for dx in range(-radius, radius + 1):
        for dy in range(-radius, radius + 1):
            if dx * dx + dy * dy != squared_distance:
                continue
            if dx > 0 or (dx == 0 and dy > 0):
                vectors.append((dx, dy))
    return tuple(sorted(vectors))


def directed_displacements(squared_distance: int) -> tuple[Point, ...]:
    canonical = canonical_displacements(squared_distance)
    return tuple(sorted((*canonical, *((-dx, -dy) for dx, dy in canonical))))


def count_unit_edges(points: set[Point] | tuple[Point, ...], squared_distance: int) -> int:
    """Count unordered target-distance pairs using a displacement oracle."""
    selected = set(points)
    return sum(
        (x + dx, y + dy) in selected
        for x, y in selected
        for dx, dy in canonical_displacements(squared_distance)
    )


def verify_configuration(
    points: list[Point] | tuple[Point, ...],
    squared_distance: int,
    claimed_edges: int | None = None,
) -> Verification:
    """Independently recompute all pair distances in O(n^2)."""
    normalized = []
    for point in points:
        if not isinstance(point, (list, tuple)) or len(point) != 2:
            return Verification(False, len(points), 0, squared_distance, "invalid point encoding")
        x, y = point
        if (
            not isinstance(x, int)
            or isinstance(x, bool)
            or not isinstance(y, int)
            or isinstance(y, bool)
        ):
            return Verification(False, len(points), 0, squared_distance, "coordinates must be integers")
        normalized.append((x, y))
    if squared_distance <= 0:
        return Verification(False, len(points), 0, squared_distance, "distance must be positive")
    if len(set(normalized)) != len(normalized):
        return Verification(False, len(points), 0, squared_distance, "points are not distinct")

    edges = 0
    for index, (x1, y1) in enumerate(normalized):
        for x2, y2 in normalized[index + 1 :]:
            if (x1 - x2) ** 2 + (y1 - y2) ** 2 == squared_distance:
                edges += 1
    if claimed_edges is not None and edges != claimed_edges:
        return Verification(
            False,
            len(points),
            edges,
            squared_distance,
            f"claimed {claimed_edges} edges but independently counted {edges}",
        )
    return Verification(True, len(points), edges, squared_distance, "exact integer check passed")


def square_grid(side: int) -> tuple[Point, ...]:
    if side <= 0:
        raise ValueError("side must be positive")
    return tuple((x, y) for x in range(side) for y in range(side))


def best_square_grid_baseline(side: int, max_squared_distance: int) -> dict:
    """Find the best rescaled full square grid in the preregistered radius range."""
    points = square_grid(side)
    candidates = []
    for squared_distance in range(1, max_squared_distance + 1):
        if not canonical_displacements(squared_distance):
            continue
        edges = count_unit_edges(points, squared_distance)
        candidates.append((edges, -squared_distance, squared_distance))
    _, _, best_distance = max(candidates)
    return {
        "points": points,
        "squared_distance": best_distance,
        "edges": count_unit_edges(points, best_distance),
    }


def greedy_configuration(point_count: int, squared_distance: int) -> tuple[Point, ...]:
    """Grow a connected lattice patch by maximizing newly induced edges."""
    if point_count <= 0:
        raise ValueError("point_count must be positive")
    vectors = directed_displacements(squared_distance)
    if not vectors:
        raise ValueError("squared_distance has no integer representations")

    selected = {(0, 0)}
    while len(selected) < point_count:
        candidates = {
            (x + dx, y + dy)
            for x, y in selected
            for dx, dy in vectors
            if (x + dx, y + dy) not in selected
        }

        def priority(point: Point) -> tuple[int, int, int, int, int, int, int]:
            x, y = point
            links = sum((x + dx, y + dy) in selected for dx, dy in vectors)
            return (
                links,
                -(x * x + y * y),
                -max(abs(x), abs(y)),
                -abs(x),
                -abs(y),
                -x,
                -y,
            )

        selected.add(max(candidates, key=priority))
    return tuple(sorted(selected))


def evolve_configuration(
    initial_points: tuple[Point, ...],
    squared_distance: int,
    *,
    steps: int,
    seed: int,
) -> dict:
    """Improve a configuration with reproducible, verifier-scored point swaps."""
    if steps < 0:
        raise ValueError("steps must be non-negative")
    rng = random.Random(seed)
    vectors = directed_displacements(squared_distance)
    selected_list = list(initial_points)
    selected = set(selected_list)
    current_edges = count_unit_edges(selected, squared_distance)
    best_edges = current_edges
    best_points = tuple(sorted(selected))
    accepted_swaps = 0

    def degree(point: Point, population: set[Point]) -> int:
        x, y = point
        return sum((x + dx, y + dy) in population for dx, dy in vectors)

    for step in range(steps):
        remove_index = rng.randrange(len(selected_list))
        removed = selected_list[remove_index]
        anchor = selected_list[rng.randrange(len(selected_list))]
        dx, dy = vectors[rng.randrange(len(vectors))]
        added = (anchor[0] + dx, anchor[1] + dy)
        if added in selected:
            continue

        without_removed = selected - {removed}
        delta = degree(added, without_removed) - degree(removed, selected)
        temperature = max(0.01, 2.0 * (1.0 - step / max(1, steps)))
        accept = delta >= 0 or rng.random() < 0.02 * math.exp(delta / temperature)
        if not accept:
            continue

        selected.remove(removed)
        selected.add(added)
        selected_list[remove_index] = added
        current_edges += delta
        accepted_swaps += 1
        if current_edges > best_edges:
            best_edges = current_edges
            best_points = tuple(sorted(selected))

    return {
        "points": best_points,
        "edges": best_edges,
        "seed": seed,
        "steps": steps,
        "accepted_swaps": accepted_swaps,
    }


def select_search_distances(
    point_count: int,
    max_squared_distance: int,
    limit: int,
    required: tuple[int, ...] = (),
) -> tuple[dict, ...]:
    """Rank radii by an actual greedy construction, not representation count alone."""
    candidates = []
    for squared_distance in range(1, max_squared_distance + 1):
        vector_count = len(directed_displacements(squared_distance))
        if vector_count < 8 and squared_distance not in required:
            continue
        points = greedy_configuration(point_count, squared_distance)
        candidates.append(
            {
                "squared_distance": squared_distance,
                "vector_count": vector_count,
                "greedy_edges": count_unit_edges(points, squared_distance),
                "points": points,
            }
        )
    candidates.sort(
        key=lambda item: (
            item["greedy_edges"],
            item["vector_count"],
            -item["squared_distance"],
        ),
        reverse=True,
    )
    selected = candidates[:limit]
    selected_distances = {item["squared_distance"] for item in selected}
    for distance in required:
        if distance not in selected_distances:
            match = next(item for item in candidates if item["squared_distance"] == distance)
            selected.append(match)
    return tuple(selected)


def run_search(
    *,
    sizes: tuple[int, ...] = (64, 100, 144),
    max_squared_distance: int = 325,
    candidate_limit: int = 12,
    steps: int = 30_000,
    seeds: tuple[int, ...] = (17, 43, 101),
) -> dict:
    """Run the preregistered baseline/greedy/evolution comparison."""
    studies = []
    for point_count in sizes:
        side = math.isqrt(point_count)
        if side * side != point_count:
            raise ValueError("all preregistered sizes must be perfect squares")
        grid = square_grid(side)
        axis_edges = count_unit_edges(grid, 1)
        baseline = best_square_grid_baseline(side, max_squared_distance)
        distances = select_search_distances(
            point_count,
            max_squared_distance,
            candidate_limit,
            required=(baseline["squared_distance"],),
        )

        attempts = []
        for candidate in distances:
            seed_results = [
                evolve_configuration(
                    candidate["points"],
                    candidate["squared_distance"],
                    steps=steps,
                    seed=seed,
                )
                for seed in seeds
            ]
            best = max(seed_results, key=lambda item: (item["edges"], -item["seed"]))
            attempts.append(
                {
                    "squared_distance": candidate["squared_distance"],
                    "vector_count": candidate["vector_count"],
                    "greedy_edges": candidate["greedy_edges"],
                    "seed_edges": {str(item["seed"]): item["edges"] for item in seed_results},
                    "best_seed": best["seed"],
                    "evolved_edges": best["edges"],
                    "points": list(best["points"]),
                }
            )
        winner = dict(
            max(
                attempts,
                key=lambda item: (
                    item["evolved_edges"],
                    item["greedy_edges"],
                    -item["squared_distance"],
                ),
            )
        )
        for attempt in attempts:
            attempt.pop("points")
        verification = verify_configuration(
            winner["points"], winner["squared_distance"], winner["evolved_edges"]
        )
        baseline_verification = verify_configuration(
            list(baseline["points"]), baseline["squared_distance"], baseline["edges"]
        )
        studies.append(
            {
                "point_count": point_count,
                "axis_grid_edges": axis_edges,
                "arithmetic_square_baseline": {
                    "squared_distance": baseline["squared_distance"],
                    "edges": baseline["edges"],
                    "verification": baseline_verification.__dict__,
                },
                "best_greedy_edges": max(item["greedy_edges"] for item in attempts),
                "winner": winner,
                "verification": verification.__dict__,
                "absolute_gain_over_arithmetic_square": (
                    winner["evolved_edges"] - baseline["edges"]
                ),
                "relative_gain_over_arithmetic_square": (
                    winner["evolved_edges"] / baseline["edges"] - 1.0
                ),
                "finite_effective_exponent": math.log(winner["evolved_edges"], point_count),
                "average_degree": 2.0 * winner["evolved_edges"] / point_count,
                "attempts": attempts,
            }
        )

    return {
        "experiment": "amy_finite_unit_distance_counterexample_search_v1",
        "configuration": {
            "sizes": list(sizes),
            "max_squared_distance": max_squared_distance,
            "candidate_limit": candidate_limit,
            "steps_per_seed": steps,
            "seeds": list(seeds),
        },
        "method": {
            "representation": "integer lattice coordinates scaled by 1/sqrt(squared_distance)",
            "baseline": "best complete square grid over every integer squared distance in range",
            "search": "greedy graph growth followed by seeded evolutionary point swaps",
            "verification": "independent O(n^2) exact integer squared-distance recount",
        },
        "studies": studies,
        "all_exactly_verified": all(item["verification"]["valid"] for item in studies),
        "all_improve_arithmetic_square": all(
            item["absolute_gain_over_arithmetic_square"] > 0 for item in studies
        ),
        "claim_status": {
            "replication": "finite replication of the rescaled integer-grid mechanism",
            "improvement": "finite improvement over the preregistered complete-square baseline",
            "global_novelty_certified": False,
            "asymptotic_improvement_claimed": False,
            "openai_theorem_reproved": False,
        },
    }
