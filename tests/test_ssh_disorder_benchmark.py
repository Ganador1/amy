from __future__ import annotations

import pytest

from atlas.app.ssh_disorder_benchmark import (
    BenchmarkConfig,
    condition_seed,
    diagnostic_votes,
    random_ssh_label,
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
