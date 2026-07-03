#!/usr/bin/env python3
"""Analyze E2E branch quality and propose the next scientific iteration.

This is the lightweight loop controller for A.M.Y's paper-producing branches:
read completed E2E JSON artifacts, identify the current bottleneck, and render
the next baseline/alternative/control experiment contract for each domain.
"""
from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping


QUALITY_TARGETS: dict[str, Any] = {
    "rubric_total": 90.0,
    "discussion_total": 80.0,
    "grounding_repairs": 0,
    "reflection_pass": True,
    "failed_tools": 0,
    "min_successful_tools": 3,
}

RUBRIC_DIMENSION_FLOORS: dict[str, float] = {
    "provenance_integrity": 10.0,
    "tool_diversity": 8.0,
    "falsifiability": 12.0,
    "explicit_limitations": 8.0,
    "numerical_claims_grounded": 15.0,
    "citation_accuracy": 10.0,
    "abstract_uniqueness": 10.0,
    "statistical_rigor": 7.5,
    "reproducibility_info": 10.0,
}

STOP_RULE = {
    "rubric_total": QUALITY_TARGETS["rubric_total"],
    "discussion_total": QUALITY_TARGETS["discussion_total"],
    "grounding_repairs": QUALITY_TARGETS["grounding_repairs"],
    "reflection_pass": QUALITY_TARGETS["reflection_pass"],
}

DOMAIN_BRANCH_PLAYBOOKS: dict[str, dict[str, Any]] = {
    "chemistry": {
        "objective": "Resolve whether finite-chain polyene gaps close by uniform Huckel scaling or remain finite under bond alternation.",
        "experiment_contract": [
            {
                "role": "baseline",
                "instruction": "Run uniform Huckel gap scaling across a wide even-n grid and report fitted inverse-linear residuals.",
            },
            {
                "role": "alternative_or_perturbation",
                "instruction": "Run the same grid with alternating strong/weak bonds and report the finite asymptotic gap estimate.",
            },
            {
                "role": "independent_control",
                "instruction": "Use small-polyene PySCF/HF endpoint controls plus direct Huckel endpoint calculations.",
            },
        ],
        "next_experiment": "Extend the completed chemistry branch only if a new bottleneck appears: add electron-correlation or larger PySCF controls while preserving the same uniform-vs-alternated question.",
        "stop_rule": STOP_RULE,
    },
    "mathematics": {
        "objective": "Test prime-gap scaling against explicit logarithmic and Cramer-style baselines across increasing N.",
        "experiment_contract": [
            {
                "role": "baseline",
                "instruction": "Run prime_gap_analysis at the largest feasible N grid and keep max_gap, mean_gap, and observed gap distribution.",
            },
            {
                "role": "alternative_or_perturbation",
                "instruction": "Compare observed max gaps with log(N), log(N)^2, and fitted residual models rather than only reporting more primes.",
            },
            {
                "role": "independent_control",
                "instruction": "Use SymPy prime_count/is_prime checks and a separate deterministic metric table for normalized gaps.",
            },
        ],
        "next_experiment": "Add a prime-gap model-comparison tool that emits max_gap/log(N)^2, mean_gap/log(N), fit RMSE, and residual trend; rerun mathematics with that tool plus SymPy controls.",
        "stop_rule": STOP_RULE,
    },
    "physics": {
        "objective": "Measure whether hydrogen Rydberg energy levels follow the expected inverse-square law over a controlled n grid.",
        "experiment_contract": [
            {
                "role": "baseline",
                "instruction": "Run hydrogen energy levels for n=1,2,3,5,10 and compute residuals against -13.6/n^2 eV.",
            },
            {
                "role": "alternative_or_perturbation",
                "instruction": "Add a perturbation or competing calibration model, such as a quantum-defect variant or non-hydrogenic control.",
            },
            {
                "role": "independent_control",
                "instruction": "Keep Bell/circuit checks separate as instrumentation controls and add a numerical residual table for the same physics objective.",
            },
        ],
        "next_experiment": "Create or extend a physics scaling tool that reports inverse-square residuals, RMSE, and a competing perturbation model before regenerating the paper.",
        "stop_rule": STOP_RULE,
    },
    "astronomy": {
        "objective": "Quantify where low-redshift Hubble-law distances stop matching Planck18 luminosity distances.",
        "experiment_contract": [
            {
                "role": "baseline",
                "instruction": "Run Planck18 luminosity distance for z=0.01,0.1,0.5,1,2 and keep a single distance table.",
            },
            {
                "role": "alternative_or_perturbation",
                "instruction": "Compare against the low-z Hubble-law or cosmographic approximation and report percent residuals.",
            },
            {
                "role": "independent_control",
                "instruction": "Use constants/blackbody checks only as calibration controls, not as the main objective.",
            },
        ],
        "next_experiment": "Add a cosmology residual table/tool for Planck18 versus low-z approximation; rerun astronomy with that plus one calibration control.",
        "stop_rule": STOP_RULE,
    },
    "statistics": {
        "objective": "Decide whether two synthetic measurement groups differ with effect size, uncertainty, and power controls.",
        "experiment_contract": [
            {
                "role": "baseline",
                "instruction": "Run descriptive statistics and the planned two-sample t-test on the same two groups.",
            },
            {
                "role": "alternative_or_perturbation",
                "instruction": "Add bootstrap confidence intervals or a permutation-test control for the same group difference.",
            },
            {
                "role": "independent_control",
                "instruction": "Report Cohen's d, sample size, p-value, confidence interval, and a power/simulation check.",
            },
        ],
        "next_experiment": "Add an effect-size/power or bootstrap-CI tool output, then rerun statistics without changing the objective.",
        "stop_rule": STOP_RULE,
    },
    "biology": {
        "objective": "Test whether GC-rich sequence panels are distinguishable from AT-rich controls using composition and coding-context evidence.",
        "experiment_contract": [
            {
                "role": "baseline",
                "instruction": "Run DNA composition metrics on GC-rich and AT-rich sequence panels, not only one fragment.",
            },
            {
                "role": "alternative_or_perturbation",
                "instruction": "Perturb sequence panels by length or composition and test whether the GC signal remains stable.",
            },
            {
                "role": "independent_control",
                "instruction": "Use t-tests/effect sizes plus protein/ORF or motif checks as independent biological context.",
            },
        ],
        "next_experiment": "Expand biology to paired GC-rich/AT-rich panels with effect size, p-value, and coding-context controls before another paper loop.",
        "stop_rule": STOP_RULE,
    },
}


@dataclass(frozen=True)
class Bottleneck:
    key: str
    severity: str
    observed: Any
    target: Any
    message: str


@dataclass(frozen=True)
class BranchSummary:
    path: str | None
    domain: str
    model: str | None
    publication_status: str | None
    rubric_total: float | None
    discussion_total: float | None
    grounding_repairs: int | None
    reflection_pass: bool | None
    successful_tools: int
    failed_tools: int
    meets_targets: bool
    bottlenecks: list[Bottleneck] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    objective: str = ""
    next_experiment: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


RUN_NAME_RE = re.compile(r"^e2e_(?P<domain>[a-zA-Z0-9-]+)_(?P<stamp>\d{8}_\d{6})\.json$")


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _domain_from_path(path: Path | None) -> str | None:
    if path is None:
        return None
    match = RUN_NAME_RE.match(path.name)
    return match.group("domain") if match else None


def _bottleneck(key: str, severity: str, observed: Any, target: Any, message: str) -> Bottleneck:
    return Bottleneck(
        key=key,
        severity=severity,
        observed=observed,
        target=target,
        message=message,
    )


def _actions_for(bottlenecks: list[Bottleneck], domain: str) -> list[str]:
    if not bottlenecks:
        return []

    actions: list[str] = []
    keys = {b.key for b in bottlenecks}

    if "failed_tools" in keys:
        actions.append("Fix failed tool protocols before spending another long model run.")
    if "successful_tools" in keys or "rubric_tool_diversity" in keys:
        actions.append("Add an independent control so the branch has baseline, alternative_or_perturbation, and independent control evidence.")
    if "grounding_repair" in keys:
        actions.append("Add missing numeric metrics to tool output or pass exact raw values through the paper context until grounding_repair.repairs is 0.")
    if "reflection" in keys:
        actions.append("Convert Reflection high/medium issues into explicit constraints for the next prompt before regenerating the paper.")
    if "discussion_total" in keys or "rubric_explicit_limitations" in keys:
        actions.append("Force the Discussion to state limitations, alternatives, and what the result does not claim.")
    if "rubric_falsifiability" in keys:
        actions.append("Write the competing model and measurable pass/fail criterion before the next tool run.")
    if "rubric_statistical_rigor" in keys:
        actions.append("Report uncertainty or fit quality: CI, effect size, p-value, RMSE, residual trend, or sample size as appropriate.")
    if "rubric_total" in keys:
        actions.append("Use the branch playbook as the next loop objective instead of broad domain exploration.")
    if "paper_status" in keys:
        actions.append("Fix prepublication gate failures first; a rejected paper cannot be used as a branch target.")

    playbook = DOMAIN_BRANCH_PLAYBOOKS.get(domain)
    if playbook:
        actions.append(playbook["next_experiment"])

    deduped: list[str] = []
    for action in actions:
        if action not in deduped:
            deduped.append(action)
    return deduped


def analyze_run(run: Mapping[str, Any] | str | Path, path: Path | str | None = None) -> BranchSummary:
    """Return bottlenecks and next actions for one E2E summary artifact."""
    if isinstance(run, (str, Path)):
        path_obj = Path(run)
        data = json.loads(path_obj.read_text(encoding="utf-8"))
        path = path_obj
    else:
        data = run
        path_obj = Path(path) if path is not None else None

    domain = str(data.get("domain") or _domain_from_path(path_obj) or "unknown")
    paper = data.get("paper") or {}
    rubric = data.get("rubric") or {}
    discussion = data.get("discussion") or {}
    reflection = data.get("reflection") or {}
    repair = paper.get("grounding_repair") or {}

    publication_status = paper.get("publication_status")
    rubric_total = _float_or_none(rubric.get("total"))
    discussion_total = _float_or_none(discussion.get("total"))
    grounding_repairs = _int_or_none(repair.get("repairs"))
    reflection_pass = reflection.get("pass_overall")
    if reflection_pass is not None:
        reflection_pass = bool(reflection_pass)
    successful_tools = len(data.get("tool_results") or [])
    failed_tools = len(data.get("failed_results") or [])

    bottlenecks: list[Bottleneck] = []
    if publication_status and publication_status != "published":
        bottlenecks.append(_bottleneck("paper_status", "critical", publication_status, "published", "paper was not published"))
    if failed_tools > QUALITY_TARGETS["failed_tools"]:
        bottlenecks.append(_bottleneck("failed_tools", "high", failed_tools, QUALITY_TARGETS["failed_tools"], "one or more tool calls failed"))
    if successful_tools < QUALITY_TARGETS["min_successful_tools"]:
        bottlenecks.append(_bottleneck("successful_tools", "high", successful_tools, QUALITY_TARGETS["min_successful_tools"], "not enough usable tool outputs"))
    if grounding_repairs is not None and grounding_repairs > QUALITY_TARGETS["grounding_repairs"]:
        bottlenecks.append(_bottleneck("grounding_repair", "high", grounding_repairs, QUALITY_TARGETS["grounding_repairs"], "paper needed grounding repair"))
    if reflection_pass is not None and reflection_pass is not QUALITY_TARGETS["reflection_pass"]:
        bottlenecks.append(_bottleneck("reflection", "high", reflection_pass, QUALITY_TARGETS["reflection_pass"], "reflection gate did not pass"))
    if rubric_total is None:
        bottlenecks.append(_bottleneck("rubric_total", "medium", None, QUALITY_TARGETS["rubric_total"], "rubric score missing"))
    elif rubric_total < QUALITY_TARGETS["rubric_total"]:
        bottlenecks.append(_bottleneck("rubric_total", "medium", rubric_total, QUALITY_TARGETS["rubric_total"], "rubric total below target"))
    if discussion_total is None:
        bottlenecks.append(_bottleneck("discussion_total", "medium", None, QUALITY_TARGETS["discussion_total"], "discussion score missing"))
    elif discussion_total < QUALITY_TARGETS["discussion_total"]:
        bottlenecks.append(_bottleneck("discussion_total", "medium", discussion_total, QUALITY_TARGETS["discussion_total"], "discussion score below target"))

    per_dim = rubric.get("per_dim") or {}
    for name, floor in RUBRIC_DIMENSION_FLOORS.items():
        observed = _float_or_none(per_dim.get(name))
        if observed is not None and observed < floor:
            bottlenecks.append(
                _bottleneck(
                    f"rubric_{name}",
                    "medium",
                    observed,
                    floor,
                    f"{name} below branch floor",
                )
            )

    playbook = DOMAIN_BRANCH_PLAYBOOKS.get(domain, {})
    return BranchSummary(
        path=str(path_obj) if path_obj else None,
        domain=domain,
        model=data.get("model"),
        publication_status=publication_status,
        rubric_total=rubric_total,
        discussion_total=discussion_total,
        grounding_repairs=grounding_repairs,
        reflection_pass=reflection_pass,
        successful_tools=successful_tools,
        failed_tools=failed_tools,
        meets_targets=not bottlenecks,
        bottlenecks=bottlenecks,
        next_actions=_actions_for(bottlenecks, domain),
        objective=playbook.get("objective", ""),
        next_experiment=playbook.get("next_experiment", ""),
    )


def _sort_key(path: Path) -> tuple[str, str, str]:
    match = RUN_NAME_RE.match(path.name)
    if match:
        return (match.group("domain"), match.group("stamp"), path.name)
    return ("", "", path.name)


def select_latest_per_domain(paths: Iterable[Path | str]) -> dict[str, Path]:
    """Select the most recent timestamped E2E JSON for each domain."""
    selected: dict[str, Path] = {}
    selected_stamp: dict[str, str] = {}
    for raw_path in paths:
        path = Path(raw_path)
        domain = _domain_from_path(path)
        stamp = ""
        match = RUN_NAME_RE.match(path.name)
        if match:
            stamp = match.group("stamp")
        else:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                domain = str(data.get("domain") or domain or "unknown")
            except (OSError, json.JSONDecodeError):
                domain = domain or "unknown"
            stamp = path.name
        if domain is None:
            domain = "unknown"
        if domain not in selected or stamp > selected_stamp[domain]:
            selected[domain] = path
            selected_stamp[domain] = stamp
    return selected


def _expand_inputs(inputs: list[str]) -> list[Path]:
    paths: list[Path] = []
    for item in inputs:
        path = Path(item)
        if path.is_dir():
            paths.extend(sorted(path.glob("e2e_*.json"), key=_sort_key))
        elif path.exists():
            paths.append(path)
    return sorted(paths, key=_sort_key)


def _fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.3f}".rstrip("0").rstrip(".")
    return str(value)


def format_markdown(summaries: list[BranchSummary]) -> str:
    lines = [
        "# E2E Branch Quality",
        "",
        "| domain | rubric | discussion | repairs | reflection | tools | status |",
        "| --- | ---: | ---: | ---: | --- | ---: | --- |",
    ]
    for summary in summaries:
        status = "target" if summary.meets_targets else "iterate"
        lines.append(
            "| {domain} | {rubric} | {discussion} | {repairs} | {reflection} | {tools}/{failed} | {status} |".format(
                domain=summary.domain,
                rubric=_fmt(summary.rubric_total),
                discussion=_fmt(summary.discussion_total),
                repairs=_fmt(summary.grounding_repairs),
                reflection=_fmt(summary.reflection_pass),
                tools=summary.successful_tools,
                failed=summary.failed_tools,
                status=status,
            )
        )

    for summary in summaries:
        lines.extend(["", f"## {summary.domain}", f"Objective: {summary.objective or 'n/a'}"])
        if summary.path:
            lines.append(f"Artifact: `{summary.path}`")
        if summary.bottlenecks:
            lines.append("Bottlenecks:")
            for item in summary.bottlenecks:
                lines.append(f"- {item.key}: observed={_fmt(item.observed)} target={_fmt(item.target)} ({item.message})")
        else:
            lines.append("Bottlenecks: none")
        if summary.next_actions:
            lines.append("Next actions:")
            for action in summary.next_actions:
                lines.append(f"- {action}")
        playbook = DOMAIN_BRANCH_PLAYBOOKS.get(summary.domain)
        if playbook:
            lines.append("Experiment contract:")
            for step in playbook["experiment_contract"]:
                lines.append(f"- {step['role']}: {step['instruction']}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", help="E2E JSON files or directories")
    parser.add_argument("--latest-per-domain", action="store_true", help="Analyze only the newest E2E artifact per domain")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    args = parser.parse_args()

    inputs = args.paths or ["experiments/e2e_validation"]
    paths = _expand_inputs(inputs)
    if args.latest_per_domain:
        paths = sorted(select_latest_per_domain(paths).values(), key=_sort_key)

    summaries = [analyze_run(path) for path in paths]
    if args.json:
        print(json.dumps([summary.to_dict() for summary in summaries], indent=2, ensure_ascii=False))
    else:
        print(format_markdown(summaries))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
