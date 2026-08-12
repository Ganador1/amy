#!/usr/bin/env python3
"""Run A.M.Y's finite unit-distance replication and counterexample search."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core.provenance import ProvenanceManager  # noqa: E402
from experiments.unit_distance_search.search import run_search  # noqa: E402


DEFAULT_RESULTS = ROOT / "experiments" / "unit_distance_search" / "AUDIT.json"
DEFAULT_FINDINGS = ROOT / "experiments" / "unit_distance_search" / "FINDINGS.md"


def render_findings(result: dict, provenance_id: str, result_digest: str) -> str:
    rows = []
    for study in result["studies"]:
        baseline = study["arithmetic_square_baseline"]
        winner = study["winner"]
        rows.append(
            "| {n} | {axis} | {baseline} (d²={baseline_d}) | {greedy} | "
            "{evolved} (d²={winner_d}) | {gain:.2%} | {degree:.3f} |".format(
                n=study["point_count"],
                axis=study["axis_grid_edges"],
                baseline=baseline["edges"],
                baseline_d=baseline["squared_distance"],
                greedy=study["best_greedy_edges"],
                evolved=winner["evolved_edges"],
                winner_d=winner["squared_distance"],
                gain=study["relative_gain_over_arithmetic_square"],
                degree=study["average_degree"],
            )
        )

    return f"""# A.M.Y finite unit-distance replication and search

**Run date:** {date.today().isoformat()}<br>
**Status:** exact finite computational result; not a new asymptotic theorem<br>
**Provenance ID:** `{provenance_id}`<br>
**Canonical result SHA-256:** `{result_digest}`

## Outcome

A.M.Y reproduced the rescaled integer-grid mechanism behind the classical
lower bound for the planar unit-distance problem and then searched a strictly
larger family of irregular lattice subsets. All winning edge counts were
recomputed by a separate quadratic-time verifier using exact integer squared
distances.

| Points | Axis grid | Best complete square | Best greedy | Best evolved | Gain vs complete square | Avg. degree |
|---:|---:|---:|---:|---:|---:|---:|
{chr(10).join(rows)}

The preregistered success condition was a positive gain over the best complete
square grid for every tested size. Result:
`all_improve_arithmetic_square={str(result['all_improve_arithmetic_square']).lower()}` and
`all_exactly_verified={str(result['all_exactly_verified']).lower()}`.

## What was replicated

OpenAI's May 2026 proof disproved Erdős's proposed `n^(1+o(1))` upper behavior
by constructing an infinite family through number fields. Its geometric
precursor is a rescaled integer lattice with many equal-length displacement
vectors. This experiment reproduces that precursor exactly: an integer vector
of squared length `d²` becomes a unit vector after scaling all coordinates by
`1/sqrt(d²)`.

## What A.M.Y improved

The improvement is finite and explicitly scoped. The baseline exhaustively
chooses the best squared distance for a complete square grid within the
preregistered range. A.M.Y then grows irregular graph patches and applies
seeded point-swap evolution, retaining only changes scored by the exact edge
oracle. This expands the construction family while preserving a transparent,
independently checkable certificate: the integer point list and target squared
distance.

## What is not claimed

- This does not reproduce the Golod-Shafarevich/class-field-tower proof.
- The finite effective exponents are descriptive and make no asymptotic claim.
- The configurations were not exhaustively compared with all published finite
  unit-distance records; global novelty is therefore not certified.
- A computational configuration is not a proof about `u(n)` beyond its stated
  finite lower bound.

## Workflow synthesis

The experiment combines the recent systems' strongest reusable ideas:

- OpenAI: actively search for counterexamples rather than assuming the
  prevailing conjecture is true.
- Google DeepMind Aletheia and FunSearch: generate, score, verify, and revise
  candidates, keeping executable constructions.
- Anthropic's long-running scientific workflow: use explicit test oracles,
  persistent artifacts, and independently auditable output.
- A.M.Y: exact verification, deterministic seeds, provenance records, explicit
  controls, and conservative claim boundaries in one pipeline.

## Primary sources

1. OpenAI, [Planar Point Sets with Many Unit Distances](https://cdn.openai.com/pdf/74c24085-19b0-4534-9c90-465b8e29ad73/unit-distance-proof.pdf), 2026.
2. Google DeepMind, [Accelerating Mathematical and Scientific Discovery with Gemini Deep Think](https://deepmind.google/blog/accelerating-mathematical-and-scientific-discovery-with-gemini-deep-think/), 2026.
3. Google DeepMind, [FunSearch](https://deepmind.google/blog/funsearch-making-new-discoveries-in-mathematical-sciences-using-large-language-models/), 2023.
4. Anthropic, [Long-running Claude for scientific computing](https://www.anthropic.com/research/long-running-Claude), 2026.

## Reproduce

```bash
uv run python experiments/unit_distance_search/run_experiment.py
```
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--findings", type=Path, default=DEFAULT_FINDINGS)
    parser.add_argument("--provenance-dir", type=Path, default=ROOT / "data" / "experiments")
    parser.add_argument("--steps", type=int, default=30_000)
    args = parser.parse_args()

    started = time.monotonic()
    result = run_search(steps=args.steps)
    canonical = json.dumps(result, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    elapsed = time.monotonic() - started

    provenance = ProvenanceManager(args.provenance_dir).record_execution(
        tool_name="amy_unit_distance_counterexample_search",
        tool_input=json.dumps(result["configuration"], sort_keys=True),
        tool_output=canonical,
        success=result["all_exactly_verified"],
        duration_seconds=elapsed,
        domain="mathematics",
        experiment_id="mathematics_unit_distance_search_v1",
        extra={
            "claim_status": result["claim_status"],
            "canonical_result_sha256": digest,
        },
    )
    result["provenance"] = {
        "experiment_id": provenance["experiment_id"],
        "record_hash": provenance["integrity"]["record_hash"],
        "output_hash": provenance["tool"]["output_hash"],
        "authenticated": False,
        "truth_verified": False,
    }

    args.results.parent.mkdir(parents=True, exist_ok=True)
    args.findings.parent.mkdir(parents=True, exist_ok=True)
    args.results.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    args.findings.write_text(
        render_findings(result, provenance["experiment_id"], digest), encoding="utf-8"
    )
    print(json.dumps({
        "results": str(args.results),
        "findings": str(args.findings),
        "provenance_id": provenance["experiment_id"],
        "all_exactly_verified": result["all_exactly_verified"],
        "all_improve_arithmetic_square": result["all_improve_arithmetic_square"],
        "elapsed_seconds": round(elapsed, 3),
    }, indent=2))
    return 0 if result["all_exactly_verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
