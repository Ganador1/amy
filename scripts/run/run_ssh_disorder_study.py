#!/usr/bin/env python3
"""Run the preregistered A.M.Y/Atlas SSH disorder diagnostic study."""
from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import json
import math
import os
import re
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from communication.paper_generator import PaperGenerator  # noqa: E402
from core.atlas_tools import AtlasTools, assess_tool_output  # noqa: E402
from core.provenance import ProvenanceManager  # noqa: E402


STUDY_DIR = ROOT / "experiments" / "ssh_disorder_study"
PREREGISTRATION_PATH = STUDY_DIR / "preregistration.json"
TOOL_NAME = "ssh_disorder_diagnostic_benchmark"
PRIMARY_NAMESPACE = "amy-ssh-disorder-v1-primary"
REPLICATION_NAMESPACE = "amy-ssh-disorder-v1-replication"
FULL_GRID = (
    "20,40,80;deltas=0.05,0.1,0.2;"
    "strengths=0,0.05,0.1,0.2,0.4;"
    "disorders=off_diagonal,diagonal;"
    "orientations=trivial,topological;realizations=128"
)
SMOKE_GRID = (
    "20,40;deltas=0.1;strengths=0,0.2;"
    "disorders=off_diagonal,diagonal;"
    "orientations=trivial,topological;realizations=8"
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _coerce_value(key: str, raw: str) -> Any:
    value = raw.strip()
    if key == "reference_label":
        return value
    if value == "not_defined":
        return None
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False
    if "," in value:
        parts = value.split(",")
        try:
            return [float(part) for part in parts]
        except ValueError:
            return value
    if re.fullmatch(r"[-+]?\d+", value):
        return int(value)
    if re.fullmatch(
        r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?",
        value,
    ):
        return float(value)
    return value


def _parse_semicolon_fields(text: str) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    for part in text.split(";"):
        candidate = part.strip()
        if not candidate or "=" not in candidate:
            continue
        key, value = candidate.split("=", 1)
        fields[key.strip()] = _coerce_value(key.strip(), value)
    return fields


def parse_atlas_report(text: str) -> dict[str, Any]:
    if "SSH disorder diagnostic benchmark" not in text:
        raise ValueError("Atlas output is not an SSH disorder benchmark report")
    parsed: dict[str, Any] = {"summaries": [], "pooled": None}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("namespace=") and "namespace" not in parsed:
            parsed["namespace"] = line.split("=", 1)[1]
        elif line.startswith("protocol_sha256="):
            parsed["protocol_sha256"] = line.split("=", 1)[1]
        elif line.startswith("preregistration_sha256="):
            parsed["preregistration_sha256"] = line.split("=", 1)[1]
        elif line.startswith("summary;"):
            parsed["summaries"].append(
                _parse_semicolon_fields(line.split(";", 1)[1])
            )
        elif line.startswith("pooled;"):
            parsed["pooled"] = _parse_semicolon_fields(
                line.split(";", 1)[1]
            )

    required = {
        "namespace",
        "protocol_sha256",
        "preregistration_sha256",
        "summaries",
        "pooled",
    }
    missing = sorted(required - parsed.keys())
    if missing or parsed["pooled"] is None or not parsed["summaries"]:
        raise ValueError(f"incomplete Atlas report; missing={missing}")
    for hash_key in ("protocol_sha256", "preregistration_sha256"):
        if not re.fullmatch(r"[0-9a-f]{64}", str(parsed[hash_key])):
            raise ValueError(f"invalid {hash_key} in Atlas report")
    return parsed


def validate_preregistration_hash(
    parsed: dict[str, Any],
    expected_sha256: str,
) -> None:
    observed = parsed.get("preregistration_sha256")
    if observed != expected_sha256:
        raise ValueError(
            "preregistration hash mismatch: "
            f"expected {expected_sha256}, observed {observed}"
        )


def _csv_value(value: Any) -> Any:
    if isinstance(value, (list, tuple, dict)):
        return json.dumps(value, sort_keys=True)
    if value is None:
        return ""
    return value


def write_condition_tables(
    output_dir: Path,
    runs: dict[str, dict[str, Any]],
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    for run_label, parsed in runs.items():
        for summary in parsed["summaries"]:
            rows.append({"run": run_label, **summary})

    columns: list[str] = []
    for preferred in (
        "run",
        "namespace",
        "disorder_type",
        "n",
        "delta",
        "strength",
    ):
        if any(preferred in row for row in rows):
            columns.append(preferred)
    for row in rows:
        for key in row:
            if key not in columns:
                columns.append(key)

    json_path = output_dir / "condition_summaries.json"
    csv_path = output_dir / "condition_summaries.csv"
    json_path.write_text(
        json.dumps(rows, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _csv_value(row.get(key)) for key in columns})
    return {"json": json_path, "csv": csv_path}


def evaluate_hypotheses(
    primary: dict[str, Any],
    replication: dict[str, Any],
    *,
    alpha: float,
) -> dict[str, Any]:
    primary_difference = float(primary["error_gap_minus_error_joint"])
    replication_difference = float(replication["error_gap_minus_error_joint"])
    primary_p = float(primary["mcnemar_pvalue"])
    replication_p = float(replication["mcnemar_pvalue"])
    primary_supported = primary_difference > 0.0 and primary_p < alpha
    replication_supported = (
        replication_difference > 0.0 and replication_p < alpha
    )
    h2_supported = (
        replication_difference > 0.0
        and replication_supported == primary_supported
    )
    if h2_supported:
        replication_text = (
            "The preregistered direction and H1 decision replicated."
        )
    else:
        replication_text = (
            "The preregistered replication criterion failed; no replicated "
            "superiority claim is supported."
        )
    return {
        "alpha": alpha,
        "H1_primary_supported": primary_supported,
        "H1_replication_supported": replication_supported,
        "H2_replication_supported": h2_supported,
        "primary_error_difference": primary_difference,
        "primary_mcnemar_pvalue": primary_p,
        "replication_error_difference": replication_difference,
        "replication_mcnemar_pvalue": replication_p,
        "plain_language": (
            (
                "The primary paired comparison supported H1. "
                if primary_supported
                else "The primary paired comparison did not support H1. "
            )
            + replication_text
        ),
    }


def build_manifest(root: Path, files: Iterable[Path]) -> Path:
    root = root.resolve()
    manifest_path = root / "MANIFEST.sha256"
    unique_files = sorted(
        {
            path.resolve()
            for path in files
            if path.exists() and path.resolve() != manifest_path
        },
        key=lambda path: path.relative_to(root).as_posix(),
    )
    lines = [
        f"{sha256_file(path)}  {path.relative_to(root).as_posix()}"
        for path in unique_files
    ]
    manifest_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return manifest_path


def verify_manifest(root: Path, manifest_path: Path) -> dict[str, Any]:
    root = root.resolve()
    failed: list[str] = []
    checked = 0
    for raw_line in manifest_path.read_text(encoding="utf-8").splitlines():
        if not raw_line.strip():
            continue
        expected, relative = raw_line.split("  ", 1)
        target = root / relative
        checked += 1
        if not target.is_file() or sha256_file(target) != expected:
            failed.append(relative)
    return {"ok": not failed, "checked": checked, "failed": failed}


def _tool_input(
    *,
    namespace: str,
    preregistration_sha256: str,
    smoke: bool,
) -> str:
    grid = SMOKE_GRID if smoke else FULL_GRID
    return (
        f"{grid};namespace={namespace};"
        f"protocol_sha256={preregistration_sha256}"
    )


def _copy_provenance_to_release(
    record: dict[str, Any],
    provenance: ProvenanceManager,
    release_dir: Path,
) -> Path:
    experiment_id = record["experiment_id"]
    source = provenance.base_dir / experiment_id
    target = release_dir / "provenance" / experiment_id
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target)
    return target


def _pooled_json(
    release_dir: Path,
    runs: dict[str, dict[str, Any]],
    decision: dict[str, Any],
) -> Path:
    path = release_dir / "pooled_results.json"
    payload = {
        "primary": runs["primary"]["pooled"],
        "replication": runs["replication"]["pooled"],
        "hypothesis_decisions": decision,
    }
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def _wilson_error_bounds(pooled: dict[str, Any], prefix: str) -> tuple[float, float]:
    accuracy_ci = pooled[f"{prefix}_accuracy_ci95"]
    return 1.0 - float(accuracy_ci[1]), 1.0 - float(accuracy_ci[0])


def _build_figures(
    release_dir: Path,
    runs: dict[str, dict[str, Any]],
) -> list[Path]:
    import matplotlib

    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt

    figures_dir = release_dir / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)

    labels = ["Primary", "Replication"]
    gap_errors = []
    joint_errors = []
    gap_error_bars = [[], []]
    joint_error_bars = [[], []]
    for run_label in ("primary", "replication"):
        pooled = runs[run_label]["pooled"]
        gap_error = 1.0 - float(pooled["gap_accuracy"])
        joint_error = 1.0 - float(pooled["joint_accuracy"])
        gap_low, gap_high = _wilson_error_bounds(pooled, "gap")
        joint_low, joint_high = _wilson_error_bounds(pooled, "joint")
        gap_errors.append(gap_error)
        joint_errors.append(joint_error)
        gap_error_bars[0].append(gap_error - gap_low)
        gap_error_bars[1].append(gap_high - gap_error)
        joint_error_bars[0].append(joint_error - joint_low)
        joint_error_bars[1].append(joint_high - joint_error)

    x = list(range(len(labels)))
    width = 0.34
    fig, ax = plt.subplots(figsize=(6.5, 4.2), dpi=180)
    ax.bar(
        [value - width / 2 for value in x],
        gap_errors,
        width,
        yerr=gap_error_bars,
        capsize=4,
        label="Gap-only",
        color="#d95f02",
    )
    ax.bar(
        [value + width / 2 for value in x],
        joint_errors,
        width,
        yerr=joint_error_bars,
        capsize=4,
        label="Joint 2-of-3",
        color="#1b9e77",
    )
    ax.set_xticks(x, labels)
    ax.set_ylabel("Classification error")
    ax.set_ylim(bottom=0)
    ax.set_title("Paired off-diagonal-disorder diagnostic error")
    ax.grid(True, axis="y", alpha=0.25)
    ax.legend(frameon=False)
    fig.tight_layout()
    error_path = figures_dir / "figure_1_paired_error.png"
    fig.savefig(error_path, dpi=240, bbox_inches="tight")
    plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(8.2, 3.9), dpi=180, sharey=True)
    for axis, run_label in zip(axes, ("primary", "replication")):
        diagonal = [
            row
            for row in runs[run_label]["summaries"]
            if row["disorder_type"] == "diagonal"
        ]
        strengths = sorted({float(row["strength"]) for row in diagonal})
        for metric, color, display in (
            ("gap_positive_rate", "#d95f02", "Gap-only positive"),
            ("joint_positive_rate", "#1b9e77", "Joint positive"),
        ):
            values = []
            for strength in strengths:
                selected = [
                    row for row in diagonal
                    if math.isclose(float(row["strength"]), strength)
                ]
                numerator = sum(
                    float(row[metric]) * int(row["total"]) for row in selected
                )
                denominator = sum(int(row["total"]) for row in selected)
                values.append(numerator / denominator)
            axis.plot(
                strengths,
                values,
                marker="o",
                linewidth=1.8,
                color=color,
                label=display,
            )
        axis.set_title(run_label.capitalize())
        axis.set_xlabel("Diagonal disorder strength W")
        axis.grid(True, alpha=0.25)
    axes[0].set_ylabel("Diagnostic-positive rate")
    axes[0].legend(frameon=False)
    fig.suptitle("Symmetry-breaking negative control (not topological accuracy)")
    fig.tight_layout()
    negative_path = figures_dir / "figure_2_diagonal_negative_control.png"
    fig.savefig(negative_path, dpi=240, bbox_inches="tight")
    plt.close(fig)
    return [error_path, negative_path]


def _format_ci(values: list[float] | tuple[float, float]) -> str:
    return f"[{float(values[0]):.4f}, {float(values[1]):.4f}]"


def _paper_sections(
    *,
    preregistration_sha256: str,
    runs: dict[str, dict[str, Any]],
    decision: dict[str, Any],
    experiment_ids: list[str],
    literature_result: dict[str, Any],
) -> list[dict[str, str]]:
    primary = runs["primary"]["pooled"]
    replication = runs["replication"]["pooled"]
    primary_id, replication_id = experiment_ids
    return [
        {
            "heading": "Introduction",
            "content": (
                "The Su-Schrieffer-Heeger (SSH) chain is a canonical finite "
                "one-dimensional model in which boundary termination and chiral "
                "symmetry govern mid-gap edge states. Prior work established that "
                "off-diagonal disorder can preserve chiral protection whereas "
                "onsite disorder breaks it. The unresolved operational question "
                "addressed here is narrower: how reliably do fixed, inexpensive "
                "finite-chain diagnostics recover a random-SSH reference label? "
                "We compare a frontier-gap-only rule with a joint spectral and "
                "localization rule. The candidate novelty is the preregistered, "
                "paired, hash-auditable benchmark protocol, not new SSH physics."
            ),
        },
        {
            "heading": "Methods",
            "content": (
                "We diagonalized real symmetric open-chain SSH Hamiltonians with "
                "N in {20, 40, 80}, dimerization delta in {0.05, 0.10, 0.20}, "
                "and disorder strength W in {0.00, 0.05, 0.10, 0.20, 0.40}. "
                "Each nonzero condition used 128 realizations per orientation; "
                "W=0 used one unique realization. Off-diagonal hoppings were "
                "multiplied by exp(W z_i), preserving positivity and chiral "
                "symmetry. Diagonal controls used onsite energies W|beta|z_i. "
                "Random z_i values were generated from the first 64 bits of a "
                "SHA-256 condition digest, with orientation excluded to pair "
                "the random vectors. The off-diagonal reference label was "
                "mean(log t_inter) > mean(log t_intra). No topological reference "
                "label was assigned under diagonal disorder. The gap vote used "
                "frontier splitting divided by 4|beta|delta <= 0.20; the edge "
                "vote required frontier-pair edge weight >= 0.50; the IPR vote "
                "required N times frontier-pair IPR >= 2.50. The joint rule "
                "required at least two votes. The sole confirmatory test was a "
                "two-sided exact McNemar test on pooled paired off-diagonal "
                "records at alpha=0.05. Binomial intervals are Wilson 95% "
                "intervals; the paired error-difference interval used 5,000 "
                "deterministic bootstrap resamples. No observations were excluded. "
                f"The frozen preregistration SHA-256 was {preregistration_sha256}."
            ),
        },
        {
            "heading": "Results",
            "content": (
                f"Primary run ({primary_id}): gap-only accuracy was "
                f"{float(primary['gap_accuracy']):.4f} "
                f"(95% CI {_format_ci(primary['gap_accuracy_ci95'])}); joint "
                f"accuracy was {float(primary['joint_accuracy']):.4f} "
                f"(95% CI {_format_ci(primary['joint_accuracy_ci95'])}). The "
                f"paired error difference (gap-only minus joint) was "
                f"{float(primary['error_gap_minus_error_joint']):.4f} "
                f"(bootstrap 95% CI {_format_ci(primary['error_difference_ci95'])}). "
                f"McNemar discordant counts were "
                f"{int(primary['gap_wrong_joint_right'])} gap-wrong/joint-right "
                f"and {int(primary['gap_right_joint_wrong'])} "
                f"gap-right/joint-wrong, with exact p="
                f"{float(primary['mcnemar_pvalue']):.6g}. "
                f"Replication ({replication_id}): the paired error difference "
                f"was {float(replication['error_gap_minus_error_joint']):.4f} "
                f"(95% CI {_format_ci(replication['error_difference_ci95'])}), "
                f"and exact p={float(replication['mcnemar_pvalue']):.6g}. "
                f"{decision['plain_language']} Diagonal-disorder positive rates "
                "are reported only as a symmetry-breaking negative control in "
                "the condition tables and Figure 2."
            ),
        },
        {
            "heading": "Discussion",
            "content": (
                "The paired design isolates diagnostic disagreement from changes "
                "in disorder realization. A positive error difference supports "
                "the practical use of localization information beyond gap-only "
                "screening within this finite model; it does not establish a new "
                "phase or validate a material. McNemar discordance is the relevant "
                "paired effect because both rules see the same chains. Alternative "
                "explanations include threshold dependence, finite-size "
                "hybridization, and the use of a log-geometric random-SSH label "
                "rather than a many-body or experimentally measured invariant. "
                "The diagonal negative control demonstrates why localization alone "
                "cannot be equated with topology once chiral symmetry is broken. "
                "This study does not claim a new topological phase, a new material, "
                "or experimental validation because none of those outcomes was "
                "measured."
            ),
        },
        {
            "heading": "Testable Predictions",
            "content": (
                "H1. The fixed joint rule has lower pooled error than the gap-only "
                "rule under off-diagonal disorder. Testable via: rerun the frozen "
                "grid and compare paired errors with the exact McNemar test.\n\n"
                "H2. The sign and H1 support decision reproduce under the independent "
                "namespace. Testable via: recompute all condition seeds from the "
                "published SHA-256 formula and repeat the complete analysis.\n\n"
                "H3. Diagonal-disorder diagnostic-positive rates must not be treated "
                "as topological accuracy. Testable via: restore chiral symmetry by "
                "removing onsite terms and compare against the random-SSH reference "
                "label only in that symmetry-preserving ensemble."
            ),
        },
        {
            "heading": "Limitations and Scope",
            "content": (
                "This is a noninteracting nearest-neighbor tight-binding study, "
                "not DFT, spectroscopy, transport, or a wet-lab experiment. "
                "Thresholds were fixed before production execution but remain "
                "operational choices. The random-SSH reference criterion is valid "
                "for the preregistered chiral off-diagonal ensemble and was not "
                "extended to diagonal disorder. Automated literature search found "
                f"{len(literature_result.get('papers', []))} candidate records "
                "from open indexes; absence of an exact title or keyword match is "
                "not proof of novelty. External peer review and independent code "
                "replication remain necessary."
            ),
        },
        {
            "heading": "Reproducibility and Data Availability",
            "content": (
                "The release contains the preregistration, raw Atlas outputs, "
                "condition CSV/JSON, pooled decisions, figures, literature-search "
                "record, manuscript sources, copied provenance records, and a "
                "SHA-256 manifest. Seeds are recoverable from the published "
                "namespace and condition formula. Re-running the same namespace "
                "and software stack should reproduce byte-identical Atlas text."
            ),
        },
        {
            "heading": "Declarations and AI Disclosure",
            "content": (
                "No human or animal subjects, personal data, clinical intervention, "
                "or hazardous physical experiment were involved. No external "
                "funding or conflicts of interest were declared in the computational "
                "record. A.M.Y, an automated research system, designed and executed "
                "the computational workflow under a user-specified goal; Codex "
                "implemented and audited the software and manuscript. No claim of "
                "human authorship, institutional affiliation, or independent peer "
                "review is made. Human review is required before submission."
            ),
        },
        {
            "heading": "Conclusion",
            "content": (
                f"{decision['plain_language']} The result is limited to the frozen "
                "finite-chain benchmark and should be interpreted as candidate "
                "methodological novelty pending external replication and peer review."
            ),
        },
    ]


async def _run_atlas_call(
    *,
    atlas: AtlasTools,
    provenance: ProvenanceManager,
    namespace: str,
    preregistration_sha256: str,
    smoke: bool,
    release_dir: Path,
) -> tuple[dict[str, Any], dict[str, Any], str]:
    tool_input = _tool_input(
        namespace=namespace,
        preregistration_sha256=preregistration_sha256,
        smoke=smoke,
    )
    started = time.monotonic()
    output = await asyncio.wait_for(
        atlas.run_scientific_tool(TOOL_NAME, tool_input, domain="chemistry"),
        timeout=900.0,
    )
    duration = time.monotonic() - started
    output_text = str(output)
    assessment = assess_tool_output(output_text, tool_name=TOOL_NAME)
    if not assessment["usable"]:
        raise RuntimeError(
            f"Atlas output unusable for {namespace}: {assessment['markers']}"
        )
    parsed = parse_atlas_report(output_text)
    validate_preregistration_hash(parsed, preregistration_sha256)
    record = provenance.record_execution(
        tool_name=TOOL_NAME,
        tool_input=tool_input,
        tool_output=output_text,
        success=True,
        duration_seconds=duration,
        domain="chemistry",
        experiment_id=f"chemistry_ssh_disorder_{namespace}",
        extra={
            "namespace": namespace,
            "preregistration_sha256": preregistration_sha256,
            "assessment": assessment,
            "smoke": smoke,
        },
    )
    _copy_provenance_to_release(record, provenance, release_dir)
    return parsed, record, output_text


async def run_study(*, smoke: bool = False) -> Path:
    preregistration_sha256 = sha256_file(PREREGISTRATION_PATH)
    release_dir = STUDY_DIR / ("smoke" if smoke else "release")
    release_dir.mkdir(parents=True, exist_ok=True)
    (release_dir / "preregistration.sha256").write_text(
        f"{preregistration_sha256}  preregistration.json\n",
        encoding="utf-8",
    )
    shutil.copy2(PREREGISTRATION_PATH, release_dir / "preregistration.json")

    atlas = AtlasTools()
    provenance = ProvenanceManager()
    runs: dict[str, dict[str, Any]] = {}
    records: dict[str, dict[str, Any]] = {}
    raw_outputs: dict[str, str] = {}
    try:
        for run_label, namespace in (
            ("primary", PRIMARY_NAMESPACE),
            ("replication", REPLICATION_NAMESPACE),
        ):
            parsed, record, output = await _run_atlas_call(
                atlas=atlas,
                provenance=provenance,
                namespace=namespace,
                preregistration_sha256=preregistration_sha256,
                smoke=smoke,
                release_dir=release_dir,
            )
            runs[run_label] = parsed
            records[run_label] = record
            raw_outputs[run_label] = output
            (release_dir / f"raw_{run_label}_atlas.txt").write_text(
                output,
                encoding="utf-8",
            )

        literature_result = await atlas.search_literature(
            "finite disordered SSH chain gap edge weight inverse participation "
            "ratio diagnostic off-diagonal diagonal disorder",
            domain="physics",
            max_results=20,
        )
    finally:
        await atlas.close()

    (release_dir / "literature_search.json").write_text(
        json.dumps(literature_result, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    write_condition_tables(release_dir, runs)
    decision = evaluate_hypotheses(
        runs["primary"]["pooled"],
        runs["replication"]["pooled"],
        alpha=0.05,
    )
    _pooled_json(release_dir, runs, decision)
    _build_figures(release_dir, runs)

    experiment_ids = [
        records["primary"]["experiment_id"],
        records["replication"]["experiment_id"],
    ]
    tool_results = [
        {
            "tool": TOOL_NAME,
            "description": "Primary preregistered paired SSH disorder benchmark",
            "input": _tool_input(
                namespace=PRIMARY_NAMESPACE,
                preregistration_sha256=preregistration_sha256,
                smoke=smoke,
            ),
            "result": raw_outputs["primary"],
            "success": True,
            "experiment_id": experiment_ids[0],
        },
        {
            "tool": TOOL_NAME,
            "description": "Independent hash-seed replication",
            "input": _tool_input(
                namespace=REPLICATION_NAMESPACE,
                preregistration_sha256=preregistration_sha256,
                smoke=smoke,
            ),
            "result": raw_outputs["replication"],
            "success": True,
            "experiment_id": experiment_ids[1],
        },
    ]
    title = (
        "Paired finite-chain SSH diagnostic reliability under quenched disorder"
        + (" — smoke validation" if smoke else "")
    )
    abstract = (
        "We preregistered a paired computational benchmark comparing a "
        "frontier-gap-only rule with a joint gap, edge-weight, and inverse-"
        "participation-ratio rule for finite disordered Su-Schrieffer-Heeger "
        f"chains. {decision['plain_language']} Every Atlas output, protocol, "
        "table, figure, and manuscript artifact is covered by SHA-256 provenance. "
        "The result is a finite tight-binding methodological benchmark, not a new "
        "material, experimental observation, or new topological phase."
    )
    references = [
        "Su, W. P., Schrieffer, J. R. & Heeger, A. J. (1979). Solitons in polyacetylene. Physical Review Letters, 42, 1698-1701. doi:10.1103/PhysRevLett.42.1698.",
        "Pérez-González, B., Bello, M., Gómez-León, A. & Platero, G. (2019). SSH model with long-range hoppings: topology, driving and disorder. Physical Review B, 99, 035146. doi:10.1103/PhysRevB.99.035146.",
        "Yao, Y., Schlömer, H., Ma, Z., Campos Venuti, L. & Haas, S. (2021). Topological protection of coherence in disordered open quantum systems. Physical Review A, 104, 012216. doi:10.1103/PhysRevA.104.012216.",
        "Kvande, C. I., Hill, D. B. & Blume, D. (2023). Finite SSH chains coupled to a two-level emitter: Hybridization of edge and emitter states. arXiv:2307.05824.",
        "Harris, C. R. et al. (2020). Array programming with NumPy. Nature, 585, 357-362. doi:10.1038/s41586-020-2649-2.",
        "McNemar, Q. (1947). Note on the sampling error of the difference between correlated proportions or percentages. Psychometrika, 12, 153-157. doi:10.1007/BF02295996.",
    ]
    paper_dir = release_dir / "paper"
    generator = PaperGenerator(
        enhance=False,
        include_internal_review=True,
        include_literature_audit=False,
        output_dir=paper_dir,
    )
    paper = await generator.generate_paper(
        title=title,
        abstract=abstract,
        sections=_paper_sections(
            preregistration_sha256=preregistration_sha256,
            runs=runs,
            decision=decision,
            experiment_ids=experiment_ids,
            literature_result=literature_result,
        ),
        references=references,
        knowledge_facts=[
            {
                "subject": "SSH diagnostic benchmark",
                "predicate": "preregistration_sha256",
                "object": preregistration_sha256,
                "confidence": 1.0,
            }
        ],
        experiment_ids=experiment_ids,
        domain="chemistry",
        tool_results=tool_results,
    )
    if paper.get("publication_status") != "published":
        raise RuntimeError(
            f"paper rejected by publication gate: {paper.get('rejection_reasons')}"
        )

    study_record = {
        "study_id": "amy-ssh-disorder-diagnostic-benchmark-v1",
        "smoke": smoke,
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "preregistration_sha256": preregistration_sha256,
        "experiment_ids": experiment_ids,
        "protocol_sha256": {
            label: runs[label]["protocol_sha256"]
            for label in ("primary", "replication")
        },
        "hypothesis_decisions": decision,
        "paper": paper,
    }
    (release_dir / "study_record.json").write_text(
        json.dumps(study_record, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )

    files = [
        path
        for path in release_dir.rglob("*")
        if path.is_file() and path.name != "MANIFEST.sha256"
    ]
    manifest = build_manifest(release_dir, files)
    verification = verify_manifest(release_dir, manifest)
    if not verification["ok"]:
        raise RuntimeError(f"manifest verification failed: {verification}")
    return release_dir


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="Run the reduced non-preregistered execution-path validation grid.",
    )
    args = parser.parse_args()
    release_dir = asyncio.run(run_study(smoke=args.smoke))
    print(release_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
