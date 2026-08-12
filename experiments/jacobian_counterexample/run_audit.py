#!/usr/bin/env python3
"""Generate a provenance-linked exact audit of the Alpöge-Fable map."""

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
from experiments.jacobian_counterexample.verify import run_audit  # noqa: E402


DEFAULT_RESULTS = ROOT / "experiments" / "jacobian_counterexample" / "AUDIT.json"
DEFAULT_FINDINGS = ROOT / "experiments" / "jacobian_counterexample" / "FINDINGS.md"


def render_findings(result: dict, provenance_id: str, canonical_digest: str) -> str:
    return f"""# Exact audit of the Alpöge-Fable Jacobian counterexample

**Run date:** {date.today().isoformat()}<br>
**Provenance ID:** `{provenance_id}`<br>
**Canonical result SHA-256:** `{canonical_digest}`<br>
**Status:** published result independently reproduced; no novelty claim

## Result

A.M.Y expanded the published polynomial map in exact symbolic arithmetic and
obtained `det(JF) = {result['jacobian']['determinant']}`. It also verified two
disjoint rational three-point fibers:

- Published fiber image: `{result['official_collision']['common_output']}`.
- Independent certificate image: `{result['independent_collision']['common_output']}`.

The inputs in each fiber are distinct and all substitutions are exact. A
nonzero constant Jacobian together with either collision proves that this
specific map is a Keller map that is not injective.

## Why two collision certificates

The determinant identity and the published collision suffice mathematically.
The second fiber is retained as an adversarial implementation check: a typo
that accidentally preserves one hand-picked equality is less likely to
preserve a disjoint equality with a different target. This improves audit
resilience, not the underlying theorem.

## Claim boundary

- This reproduces the explicit dimension-three counterexample.
- It does not claim A.M.Y discovered the map or a new family.
- It does not resolve the remaining two-dimensional Jacobian conjecture.
- SymPy is the computational oracle; the result is not a Lean formalization.

## Primary sources

1. Gao, [Counterexamples to the Jacobian conjecture in dimensions greater than two](https://arxiv.org/abs/2608.00222), 2026.
2. Fong and Fable, [The State of the Jacobian Conjectures](https://jacobianconjectures.com/jacobian/note/), 2026.

## Reproduce

```bash
uv run python experiments/jacobian_counterexample/run_audit.py
```
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--findings", type=Path, default=DEFAULT_FINDINGS)
    parser.add_argument("--provenance-dir", type=Path, default=ROOT / "data" / "experiments")
    args = parser.parse_args()

    started = time.monotonic()
    result = run_audit()
    canonical = json.dumps(result, sort_keys=True, separators=(",", ":"))
    canonical_digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    elapsed = time.monotonic() - started
    provenance = ProvenanceManager(args.provenance_dir).record_execution(
        tool_name="amy_alpoge_fable_exact_audit",
        tool_input="published polynomial map and two rational collision certificates",
        tool_output=canonical,
        success=result["counterexample_conditions_verified"],
        duration_seconds=elapsed,
        domain="mathematics",
        experiment_id="mathematics_jacobian_counterexample_audit_v1",
        extra={
            "claim_status": result["claim_status"],
            "canonical_result_sha256": canonical_digest,
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
        render_findings(result, provenance["experiment_id"], canonical_digest),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "results": str(args.results),
                "findings": str(args.findings),
                "provenance_id": provenance["experiment_id"],
                "counterexample_conditions_verified": result[
                    "counterexample_conditions_verified"
                ],
                "elapsed_seconds": round(elapsed, 3),
            },
            indent=2,
        )
    )
    return 0 if result["counterexample_conditions_verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
