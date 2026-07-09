"""Deterministic finite-chain SSH disorder diagnostic benchmark.

The module is deliberately independent of Atlas process state.  Atlas exposes
it through a thin string-protocol adapter in ``run_agent_with_tools_legacy``.
"""
from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from typing import Sequence


_DISORDER_TYPES = frozenset({"off_diagonal", "diagonal"})
_ORIENTATIONS = frozenset({"trivial", "topological"})
_SHA256_RE = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True)
class BenchmarkConfig:
    lengths: tuple[int, ...]
    deltas: tuple[float, ...]
    strengths: tuple[float, ...]
    disorder_types: tuple[str, ...]
    orientations: tuple[str, ...]
    realizations: int
    namespace: str
    beta: float = -2.5
    edge_sites: int = 2
    gap_threshold: float = 0.20
    edge_threshold: float = 0.50
    ipr_threshold: float = 2.50
    protocol_sha256: str = ""

    def __post_init__(self) -> None:
        if not self.lengths or any(n < 4 or n % 2 for n in self.lengths):
            raise ValueError("lengths must contain even integers >= 4")
        if not self.deltas or any(not 0.0 < delta < 1.0 for delta in self.deltas):
            raise ValueError("deltas must lie strictly between 0 and 1")
        if not self.strengths or any(strength < 0.0 for strength in self.strengths):
            raise ValueError("strengths must be non-negative")
        if (
            not self.disorder_types
            or set(self.disorder_types) - _DISORDER_TYPES
        ):
            raise ValueError(
                "disorder_types must contain only off_diagonal or diagonal"
            )
        if not self.orientations or set(self.orientations) - _ORIENTATIONS:
            raise ValueError(
                "orientations must contain only trivial or topological"
            )
        if self.realizations <= 0:
            raise ValueError("realizations must be positive")
        if not self.namespace.strip():
            raise ValueError("namespace must be non-empty")
        if not math.isfinite(self.beta) or self.beta == 0.0:
            raise ValueError("beta must be a finite nonzero value")
        if self.edge_sites <= 0 or 2 * self.edge_sites > min(self.lengths):
            raise ValueError("edge_sites must fit within the shortest chain")
        if self.gap_threshold < 0.0:
            raise ValueError("gap_threshold must be non-negative")
        if not 0.0 <= self.edge_threshold <= 1.0:
            raise ValueError("edge_threshold must lie in [0, 1]")
        if self.ipr_threshold <= 0.0:
            raise ValueError("ipr_threshold must be positive")
        if self.protocol_sha256 and not _SHA256_RE.fullmatch(
            self.protocol_sha256.lower()
        ):
            raise ValueError("protocol_sha256 must be a 64-character hex digest")


def _canonical_float(value: float) -> str:
    return format(float(value), ".17g")


def condition_seed(
    config: BenchmarkConfig,
    disorder_type: str,
    n: int,
    delta: float,
    strength: float,
    realization_index: int,
    orientation: str,
) -> int:
    """Return a stable seed, paired by deliberately excluding orientation."""
    if orientation not in _ORIENTATIONS:
        raise ValueError(f"unknown orientation: {orientation}")
    components = (
        config.namespace,
        disorder_type,
        str(int(n)),
        _canonical_float(delta),
        _canonical_float(strength),
        str(int(realization_index)),
    )
    digest = hashlib.sha256("|".join(components).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big", signed=False)


def random_ssh_label(hoppings: Sequence[float]) -> bool:
    """Classify a chiral random SSH chain from geometric-mean hoppings."""
    values = [float(value) for value in hoppings]
    if len(values) < 3:
        raise ValueError("at least three hoppings are required")
    if any(not math.isfinite(value) or value <= 0.0 for value in values):
        raise ValueError("all hoppings must be finite and strictly positive")
    intracell = values[0::2]
    intercell = values[1::2]
    mean_log_intra = sum(math.log(value) for value in intracell) / len(intracell)
    mean_log_inter = sum(math.log(value) for value in intercell) / len(intercell)
    return mean_log_inter > mean_log_intra


def diagnostic_votes(
    *,
    gap_ratio: float,
    edge_weight: float,
    normalized_ipr: float,
    gap_threshold: float,
    edge_threshold: float,
    ipr_threshold: float,
) -> dict[str, bool]:
    """Apply the preregistered gap-only and two-of-three joint diagnostics."""
    gap_vote = float(gap_ratio) <= float(gap_threshold)
    edge_vote = float(edge_weight) >= float(edge_threshold)
    ipr_vote = float(normalized_ipr) >= float(ipr_threshold)
    return {
        "gap": gap_vote,
        "edge": edge_vote,
        "ipr": ipr_vote,
        "gap_only": gap_vote,
        "joint": sum((gap_vote, edge_vote, ipr_vote)) >= 2,
    }
