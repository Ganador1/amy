"""Deterministic finite-chain SSH disorder diagnostic benchmark.

The module is deliberately independent of Atlas process state.  Atlas exposes
it through a thin string-protocol adapter in ``run_agent_with_tools_legacy``.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass
from itertools import product
from typing import Any, Sequence

import numpy as np


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


def _clean_hoppings(
    n: int, delta: float, orientation: str, beta: float
) -> np.ndarray:
    t0 = abs(float(beta))
    strong = t0 * (1.0 + float(delta))
    weak = t0 * (1.0 - float(delta))
    starts_strong = orientation == "trivial"
    return np.asarray(
        [
            strong if ((index % 2 == 0) == starts_strong) else weak
            for index in range(n - 1)
        ],
        dtype=float,
    )


def build_realization(
    config: BenchmarkConfig,
    disorder_type: str,
    n: int,
    delta: float,
    strength: float,
    realization_index: int,
    orientation: str,
) -> tuple[np.ndarray, np.ndarray, int]:
    """Construct paired onsite and hopping arrays for one finite chain."""
    if disorder_type not in _DISORDER_TYPES:
        raise ValueError(f"unknown disorder type: {disorder_type}")
    if orientation not in _ORIENTATIONS:
        raise ValueError(f"unknown orientation: {orientation}")
    seed = condition_seed(
        config,
        disorder_type,
        n,
        delta,
        strength,
        realization_index,
        orientation,
    )
    rng = np.random.default_rng(seed)
    bond_noise = rng.uniform(-1.0, 1.0, size=n - 1)
    onsite_noise = rng.uniform(-1.0, 1.0, size=n)
    hoppings = _clean_hoppings(n, delta, orientation, config.beta)
    onsite = np.zeros(n, dtype=float)
    if disorder_type == "off_diagonal":
        hoppings = hoppings * np.exp(float(strength) * bond_noise)
    else:
        onsite = float(strength) * abs(config.beta) * onsite_noise
    return onsite, hoppings, seed


def frontier_metrics(
    onsite: Sequence[float],
    hoppings: Sequence[float],
    edge_sites: int,
) -> dict[str, float]:
    """Return frontier splitting and localization metrics."""
    onsite_array = np.asarray(onsite, dtype=float)
    hopping_array = np.asarray(hoppings, dtype=float)
    n = int(onsite_array.size)
    if n < 4 or n % 2:
        raise ValueError("onsite must describe an even chain with at least 4 sites")
    if hopping_array.shape != (n - 1,):
        raise ValueError("hoppings must have length n-1")
    if edge_sites <= 0 or 2 * edge_sites > n:
        raise ValueError("edge_sites must fit within the chain")

    hamiltonian = np.diag(onsite_array)
    hamiltonian += np.diag(-hopping_array, 1)
    hamiltonian += np.diag(-hopping_array, -1)
    energies, eigenvectors = np.linalg.eigh(hamiltonian)
    frontier_indices = (n // 2 - 1, n // 2)
    edge_weights: list[float] = []
    iprs: list[float] = []
    for index in frontier_indices:
        probabilities = np.square(np.abs(eigenvectors[:, index]))
        edge_weights.append(
            float(
                probabilities[:edge_sites].sum()
                + probabilities[-edge_sites:].sum()
            )
        )
        iprs.append(float(np.square(probabilities).sum()))
    ipr = float(np.mean(iprs))
    return {
        "frontier_splitting": float(
            energies[frontier_indices[1]] - energies[frontier_indices[0]]
        ),
        "edge_weight": float(np.mean(edge_weights)),
        "ipr": ipr,
        "normalized_ipr": float(n * ipr),
    }


def wilson_interval(
    successes: int,
    total: int,
    z: float = 1.959963984540054,
) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion."""
    if total <= 0 or successes < 0 or successes > total:
        raise ValueError("require 0 <= successes <= total and total > 0")
    proportion = successes / total
    z2 = z * z
    denominator = 1.0 + z2 / total
    center = (proportion + z2 / (2.0 * total)) / denominator
    half_width = (
        z
        * math.sqrt(
            proportion * (1.0 - proportion) / total
            + z2 / (4.0 * total * total)
        )
        / denominator
    )
    return (
        min(proportion, max(0.0, center - half_width)),
        max(proportion, min(1.0, center + half_width)),
    )


def exact_mcnemar_pvalue(
    gap_wrong_joint_right: int,
    gap_right_joint_wrong: int,
) -> float:
    """Two-sided exact McNemar p-value from discordant paired outcomes."""
    b = int(gap_wrong_joint_right)
    c = int(gap_right_joint_wrong)
    if b < 0 or c < 0:
        raise ValueError("discordant counts must be non-negative")
    discordant = b + c
    if discordant == 0:
        return 1.0
    lower = min(b, c)
    tail = sum(math.comb(discordant, k) for k in range(lower + 1))
    return min(1.0, 2.0 * tail / (2**discordant))


def _protocol_dict(config: BenchmarkConfig) -> dict[str, Any]:
    values = asdict(config)
    preregistration_sha256 = values.pop("protocol_sha256")
    values["seed_derivation"] = (
        "first_unsigned_64_bits_of_sha256("
        "namespace|disorder_type|N|delta|W|realization_index)"
    )
    values["paired_orientations"] = True
    values["preregistration_sha256"] = preregistration_sha256
    return values


def _protocol_hash(protocol: dict[str, Any]) -> str:
    encoded = json.dumps(
        protocol,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _bootstrap_error_difference_ci(
    records: Sequence[dict[str, Any]],
    namespace: str,
    label: str,
    resamples: int = 5000,
) -> tuple[float, float]:
    differences = np.asarray(
        [
            int(record["gap_wrong"]) - int(record["joint_wrong"])
            for record in records
        ],
        dtype=int,
    )
    counts = np.asarray(
        [
            int(np.sum(differences == -1)),
            int(np.sum(differences == 0)),
            int(np.sum(differences == 1)),
        ],
        dtype=int,
    )
    seed_digest = hashlib.sha256(f"{namespace}|{label}|bootstrap".encode()).digest()
    seed = int.from_bytes(seed_digest[:8], "big", signed=False)
    sampled = np.random.default_rng(seed).multinomial(
        len(differences),
        counts / len(differences),
        size=resamples,
    )
    estimates = (sampled[:, 2] - sampled[:, 0]) / len(differences)
    low, high = np.quantile(estimates, [0.025, 0.975])
    return float(low), float(high)


def _classification_summary(
    records: Sequence[dict[str, Any]],
    *,
    namespace: str,
    label: str,
) -> dict[str, Any]:
    total = len(records)
    if total == 0:
        raise ValueError("classification summary requires records")
    gap_correct = sum(not record["gap_wrong"] for record in records)
    joint_correct = sum(not record["joint_wrong"] for record in records)
    positives = [record for record in records if record["reference_label"]]
    negatives = [record for record in records if not record["reference_label"]]
    gap_fp = sum(record["gap_only_prediction"] for record in negatives)
    joint_fp = sum(record["joint_prediction"] for record in negatives)
    gap_fn = sum(not record["gap_only_prediction"] for record in positives)
    joint_fn = sum(not record["joint_prediction"] for record in positives)
    b = sum(
        record["gap_wrong"] and not record["joint_wrong"]
        for record in records
    )
    c = sum(
        not record["gap_wrong"] and record["joint_wrong"]
        for record in records
    )
    gap_errors = total - gap_correct
    joint_errors = total - joint_correct
    return {
        "total": total,
        "reference_positive": len(positives),
        "reference_negative": len(negatives),
        "gap_accuracy": gap_correct / total,
        "gap_accuracy_ci95": wilson_interval(gap_correct, total),
        "joint_accuracy": joint_correct / total,
        "joint_accuracy_ci95": wilson_interval(joint_correct, total),
        "gap_false_positive_rate": gap_fp / len(negatives) if negatives else None,
        "gap_false_positive_rate_ci95": (
            wilson_interval(gap_fp, len(negatives)) if negatives else None
        ),
        "joint_false_positive_rate": (
            joint_fp / len(negatives) if negatives else None
        ),
        "joint_false_positive_rate_ci95": (
            wilson_interval(joint_fp, len(negatives)) if negatives else None
        ),
        "gap_false_negative_rate": gap_fn / len(positives) if positives else None,
        "gap_false_negative_rate_ci95": (
            wilson_interval(gap_fn, len(positives)) if positives else None
        ),
        "joint_false_negative_rate": (
            joint_fn / len(positives) if positives else None
        ),
        "joint_false_negative_rate_ci95": (
            wilson_interval(joint_fn, len(positives)) if positives else None
        ),
        "gap_errors": gap_errors,
        "joint_errors": joint_errors,
        "error_gap_minus_error_joint": (
            gap_errors - joint_errors
        ) / total,
        "error_difference_ci95": _bootstrap_error_difference_ci(
            records,
            namespace,
            label,
        ),
        "gap_wrong_joint_right": b,
        "gap_right_joint_wrong": c,
        "mcnemar_pvalue": exact_mcnemar_pvalue(b, c),
        "reference_label_flips_from_clean_parent": sum(
            record["reference_label"] != record["clean_parent_label"]
            for record in records
        ),
    }


def _negative_control_summary(
    records: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    total = len(records)
    gap_positive = sum(record["gap_only_prediction"] for record in records)
    joint_positive = sum(record["joint_prediction"] for record in records)
    return {
        "total": total,
        "reference_positive": None,
        "reference_negative": None,
        "gap_positive_rate": gap_positive / total,
        "gap_positive_rate_ci95": wilson_interval(gap_positive, total),
        "joint_positive_rate": joint_positive / total,
        "joint_positive_rate_ci95": wilson_interval(joint_positive, total),
        "gap_accuracy": None,
        "gap_accuracy_ci95": None,
        "joint_accuracy": None,
        "joint_accuracy_ci95": None,
        "gap_false_positive_rate": None,
        "gap_false_positive_rate_ci95": None,
        "joint_false_positive_rate": None,
        "joint_false_positive_rate_ci95": None,
        "gap_false_negative_rate": None,
        "gap_false_negative_rate_ci95": None,
        "joint_false_negative_rate": None,
        "joint_false_negative_rate_ci95": None,
        "gap_errors": None,
        "joint_errors": None,
        "error_gap_minus_error_joint": None,
        "error_difference_ci95": None,
        "gap_wrong_joint_right": None,
        "gap_right_joint_wrong": None,
        "mcnemar_pvalue": None,
        "reference_label_flips_from_clean_parent": None,
    }


def run_benchmark(config: BenchmarkConfig) -> dict[str, Any]:
    """Execute the complete preregistered benchmark in memory."""
    protocol = _protocol_dict(config)
    protocol_sha256 = _protocol_hash(protocol)
    records: list[dict[str, Any]] = []
    for disorder_type, n, delta, strength in product(
        config.disorder_types,
        config.lengths,
        config.deltas,
        config.strengths,
    ):
        effective_realizations = 1 if strength == 0.0 else config.realizations
        for realization_index in range(effective_realizations):
            for orientation in config.orientations:
                onsite, hoppings, seed = build_realization(
                    config,
                    disorder_type,
                    n,
                    delta,
                    strength,
                    realization_index,
                    orientation,
                )
                metrics = frontier_metrics(
                    onsite,
                    hoppings,
                    config.edge_sites,
                )
                clean_bulk_gap = 4.0 * abs(config.beta) * delta
                gap_ratio = metrics["frontier_splitting"] / clean_bulk_gap
                votes = diagnostic_votes(
                    gap_ratio=gap_ratio,
                    edge_weight=metrics["edge_weight"],
                    normalized_ipr=metrics["normalized_ipr"],
                    gap_threshold=config.gap_threshold,
                    edge_threshold=config.edge_threshold,
                    ipr_threshold=config.ipr_threshold,
                )
                reference_label = (
                    random_ssh_label(hoppings)
                    if disorder_type == "off_diagonal"
                    else None
                )
                gap_wrong = (
                    votes["gap_only"] != reference_label
                    if reference_label is not None
                    else None
                )
                joint_wrong = (
                    votes["joint"] != reference_label
                    if reference_label is not None
                    else None
                )
                records.append(
                    {
                        "namespace": config.namespace,
                        "protocol_sha256": protocol_sha256,
                        "preregistration_sha256": config.protocol_sha256 or None,
                        "disorder_type": disorder_type,
                        "n": n,
                        "delta": delta,
                        "strength": strength,
                        "orientation": orientation,
                        "realization_index": realization_index,
                        "seed": seed,
                        "clean_parent_label": orientation == "topological",
                        "reference_label": reference_label,
                        "frontier_splitting": metrics["frontier_splitting"],
                        "clean_bulk_gap": clean_bulk_gap,
                        "gap_ratio": gap_ratio,
                        "edge_weight": metrics["edge_weight"],
                        "ipr": metrics["ipr"],
                        "normalized_ipr": metrics["normalized_ipr"],
                        "gap_vote": votes["gap"],
                        "edge_vote": votes["edge"],
                        "ipr_vote": votes["ipr"],
                        "gap_only_prediction": votes["gap_only"],
                        "joint_prediction": votes["joint"],
                        "gap_wrong": gap_wrong,
                        "joint_wrong": joint_wrong,
                    }
                )

    summaries: list[dict[str, Any]] = []
    for disorder_type, n, delta, strength in product(
        config.disorder_types,
        config.lengths,
        config.deltas,
        config.strengths,
    ):
        selected = [
            record
            for record in records
            if record["disorder_type"] == disorder_type
            and record["n"] == n
            and record["delta"] == delta
            and record["strength"] == strength
        ]
        if disorder_type == "off_diagonal":
            summary = _classification_summary(
                selected,
                namespace=config.namespace,
                label=f"{disorder_type}|{n}|{delta}|{strength}",
            )
            reference_name = "random_ssh_log_geometric_mean"
        else:
            summary = _negative_control_summary(selected)
            reference_name = "not_defined"
        summaries.append(
            {
                "namespace": config.namespace,
                "protocol_sha256": protocol_sha256,
                "preregistration_sha256": config.protocol_sha256 or None,
                "disorder_type": disorder_type,
                "n": n,
                "delta": delta,
                "strength": strength,
                "effective_realizations_per_orientation": (
                    1 if strength == 0.0 else config.realizations
                ),
                "reference_label": reference_name,
                **summary,
            }
        )

    off_diagonal_records = [
        record
        for record in records
        if record["disorder_type"] == "off_diagonal"
    ]
    pooled = _classification_summary(
        off_diagonal_records,
        namespace=config.namespace,
        label="pooled_off_diagonal",
    )
    pooled.update(
        {
            "namespace": config.namespace,
            "protocol_sha256": protocol_sha256,
            "preregistration_sha256": config.protocol_sha256 or None,
            "disorder_type": "off_diagonal",
            "reference_label": "random_ssh_log_geometric_mean",
            "primary_estimand": "error_gap_minus_error_joint",
        }
    )
    return {
        "protocol": protocol,
        "protocol_sha256": protocol_sha256,
        "preregistration_sha256": config.protocol_sha256 or None,
        "records": records,
        "summaries": summaries,
        "pooled": pooled,
    }


def _format_value(value: Any) -> str:
    if value is None:
        return "not_defined"
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, float):
        return f"{value:.10g}"
    if isinstance(value, (tuple, list)):
        return ",".join(_format_value(item) for item in value)
    return str(value)


def _format_fields(row: dict[str, Any], fields: Sequence[str]) -> str:
    return "; ".join(
        f"{field}={_format_value(row.get(field))}" for field in fields
    )


def format_benchmark_report(result: dict[str, Any]) -> str:
    """Format deterministic, parseable condition summaries for Atlas."""
    protocol = result["protocol"]
    lines = [
        "SSH disorder diagnostic benchmark:",
        "  Method: exact diagonalization of paired finite open SSH chains.",
        "  seed_derivation=sha256",
        "  paired_orientations=true",
        "  primary_estimand=error_gap_minus_error_joint",
        f"  namespace={protocol['namespace']}",
        f"  protocol_sha256={result['protocol_sha256']}",
        "  preregistration_sha256="
        f"{_format_value(result.get('preregistration_sha256'))}",
        "  Diagnostic thresholds: "
        f"gap_ratio<={_format_value(protocol['gap_threshold'])}; "
        f"edge_weight>={_format_value(protocol['edge_threshold'])}; "
        f"normalized_ipr>={_format_value(protocol['ipr_threshold'])}; "
        "joint_rule=at_least_two_of_three",
        "  Condition summaries:",
    ]
    summary_fields = (
        "namespace",
        "disorder_type",
        "n",
        "delta",
        "strength",
        "effective_realizations_per_orientation",
        "reference_label",
        "total",
        "gap_accuracy",
        "joint_accuracy",
        "gap_positive_rate",
        "joint_positive_rate",
        "gap_false_positive_rate",
        "joint_false_positive_rate",
        "gap_false_negative_rate",
        "joint_false_negative_rate",
        "error_gap_minus_error_joint",
        "gap_wrong_joint_right",
        "gap_right_joint_wrong",
        "mcnemar_pvalue",
        "reference_label_flips_from_clean_parent",
    )
    lines.extend(
        f"    summary; {_format_fields(row, summary_fields)}"
        for row in result["summaries"]
    )
    pooled_fields = (
        "namespace",
        "disorder_type",
        "reference_label",
        "total",
        "gap_accuracy",
        "gap_accuracy_ci95",
        "joint_accuracy",
        "joint_accuracy_ci95",
        "error_gap_minus_error_joint",
        "error_difference_ci95",
        "gap_wrong_joint_right",
        "gap_right_joint_wrong",
        "mcnemar_pvalue",
        "reference_label_flips_from_clean_parent",
    )
    lines.append(
        f"  pooled; {_format_fields(result['pooled'], pooled_fields)}"
    )
    lines.extend(
        [
            "  Inference scope: the exact McNemar test is confirmatory only "
            "for the pooled off-diagonal-disorder comparison.",
            "  Negative control: diagonal-disorder positive rates are "
            "descriptive because chiral topological reference_label=not_defined.",
            "  Non-claim: this tight-binding computation is not an "
            "experimental material result or a newly discovered topological phase.",
        ]
    )
    return "\n".join(lines)
