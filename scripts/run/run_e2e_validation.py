#!/usr/bin/env python3
"""E2E scientific-pipeline validation for the production A.M.Y path.

For one domain this script exercises the complete local production flow:

1. Run real Atlas tools through the persistent worker.
2. Record SHA-256 provenance for every successful tool output.
3. Generate a paper with the same PaperGenerator/Enhancer path A.M.Y uses.
4. Verify provenance hashes, Reflection, full rubric, and Discussion rubric.

The last printed line is a JSON path that another agent can audit.

Usage:
    .venv/bin/python scripts/run/run_e2e_validation.py --domain mathematics
    .venv/bin/python scripts/run/run_e2e_validation.py --domain mathematics --model glm-5.2
    .venv/bin/python scripts/run/run_e2e_validation.py --list
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.atlas_tools import AtlasTools, assess_tool_output  # noqa: E402
from core.provenance import ProvenanceManager  # noqa: E402
from communication.paper_generator import PaperGenerator  # noqa: E402
from cognition.reflection_agent import reflect  # noqa: E402

try:
    from experiments.ab_test.scoring.score_discussion import score_discussion
    from experiments.ab_test.scoring.score_paper import score_paper
except Exception:  # pragma: no cover - optional local scoring path
    score_discussion = None
    score_paper = None


OUT_DIR = ROOT / "experiments" / "e2e_validation"
PAPERS_DIR = OUT_DIR / "papers"
OUT_DIR.mkdir(parents=True, exist_ok=True)
PAPERS_DIR.mkdir(parents=True, exist_ok=True)


DOMAIN_PLANS: dict[str, dict[str, Any]] = {
    "mathematics": {
        "topic": "Prime gap scaling against logarithmic model controls",
        "calls": [
            ("prime_gap_analysis", "100000", "Prime gap analysis up to 1e5"),
            ("prime_gap_analysis", "1000000", "Prime gap analysis up to 1e6"),
            (
                "prime_gap_model_comparison",
                "10000,100000,1000000",
                "Prime-gap model comparison against log(N) and log(N)^2 controls",
            ),
            ("sympy_prime_analysis", "prime_count:1000000", "SymPy prime-count control at 1e6"),
        ],
    },
    "chemistry": {
        "topic": "SSH polyene finite-chain identifiability: Peierls gaps versus edge-state contamination",
        "calls": [
            (
                "ssh_disorder_diagnostic_benchmark",
                "20,40,80;deltas=0.05,0.1,0.2;"
                "strengths=0,0.05,0.1,0.2,0.4;"
                "disorders=off_diagonal,diagonal;"
                "orientations=trivial,topological;realizations=128;"
                "namespace=amy-ssh-disorder-v1-primary",
                "Primary paired benchmark of gap-only versus joint SSH edge-state diagnostics under disorder",
            ),
            (
                "ssh_disorder_diagnostic_benchmark",
                "20,40,80;deltas=0.05,0.1,0.2;"
                "strengths=0,0.05,0.1,0.2,0.4;"
                "disorders=off_diagonal,diagonal;"
                "orientations=trivial,topological;realizations=128;"
                "namespace=amy-ssh-disorder-v1-replication",
                "Independent hash-seed replication of the paired SSH disorder diagnostic benchmark",
            ),
            (
                "ssh_polyene_gap_map",
                "4,6,8,10,12,16,20,30,40,60,80,100;deltas=0,0.025,0.05,0.1,0.2,0.4;orientations=trivial,topological;beta=-2.5;threshold=0.05",
                "SSH finite-chain gap identifiability map across Peierls alternation and boundary orientation",
            ),
            (
                "ssh_edge_localization_map",
                "16,20,30,40,60,80,100;deltas=0.025,0.05,0.1,0.2,0.4;orientations=trivial,topological;beta=-2.5;edge_sites=2;localization_threshold=0.25;min_localization_n=16",
                "SSH frontier-state localization map using edge weights and inverse participation ratio",
            ),
            (
                "huckel_polyene_scaling",
                "4,6,8,10,12,16,20,30,40,50,80,100",
                "Huckel HOMO-LUMO gap scaling model comparison for linear polyenes",
            ),
            (
                "bond_alternated_polyene_scaling",
                "4,6,8,10,12,16,20,30,40,50,80,100;strong=-2.7;weak=-2.3",
                "Bond-alternated tight-binding gap scaling for the same finite chain lengths",
            ),
            (
                "pyscf_polyene_hf_gap",
                "4,6;basis=sto-3g",
                "Small-polyene RHF/STO-3G HOMO-LUMO gap control for C4H6 and C6H8",
            ),
            ("molecular_orbital_energy", "4:1.4", "Four-site Huckel endpoint/control calculation"),
            ("molecular_orbital_energy", "20:1.4", "Twenty-site Huckel endpoint/control calculation"),
        ],
    },
    "physics": {
        "topic": "Hydrogen Rydberg inverse-square scaling against perturbation controls",
        "calls": [
            (
                "rydberg_scaling_comparison",
                "1,2,3,5,10,20;delta=0.05",
                "Hydrogen inverse-square Rydberg scaling model comparison",
            ),
            ("quantum_energy_levels", "hydrogen:5", "Hydrogen endpoint/control energy level at n=5"),
            ("quantum_energy_levels", "hydrogen:20", "Hydrogen endpoint/control energy level at n=20"),
            ("quantum_circuit", "bell:2", "Bell-state circuit as an independent quantum-control check"),
        ],
    },
    "astronomy": {
        "topic": "Planck18 luminosity-distance residuals against low-redshift Hubble-law controls",
        "calls": [
            (
                "cosmology_residual_comparison",
                "0.01,0.1,0.5,1,2;threshold=5",
                "Planck18 luminosity-distance residual table versus low-z approximations",
            ),
            ("astropy_cosmology", "luminosity_distance:1.0", "AstroPy Planck18 z=1 luminosity-distance endpoint control"),
            ("astropy_blackbody", "5778", "Solar blackbody calibration control"),
            ("astropy_constants", "c", "Speed-of-light constant calibration"),
        ],
    },
    "statistics": {
        "topic": "Two-sample inference with effect size and uncertainty controls",
        "calls": [
            ("numpy_statistics", "summary:[12.1,11.8,12.4,12.0,11.9,12.3,12.2]", "Series A descriptive statistics"),
            ("hypothesis_tester", "ttest:[12.1,11.8,12.4,12.0]:[12.9,13.1,12.7,13.0]", "Two-sample t-test"),
            (
                "two_sample_effect_power",
                "[12.1,11.8,12.4,12.0];[12.9,13.1,12.7,13.0]",
                "Two-sample effect size, confidence interval, bootstrap CI, and observed power",
            ),
            ("numpy_correlation", "correlation:[1,2,3,4,5]:[2,4,6,8,10]", "Positive-control Pearson correlation"),
        ],
    },
    "biology": {
        "topic": "GC-rich versus AT-rich sequence panels with coding-context controls",
        "calls": [
            (
                "gc_at_panel_comparison",
                "gc=ATGGCGGCGGCGGCGGCGGCGGCGGCGTAA,ATGGCGGCGGCGGCGGCGGCGGCGGCATGA,ATGGCGGCGGCGGCGGCGGCGGCAGAATAG,ATGGCGGCGGCGGCGGCGGCGGCCGATTGA;"
                "at=ATGATAATAATAATAATAATAATAATATAA,ATGATTATTATTATTATTATTATTATATAG,ATGAATAATAATAATAATAATAATATTTGA,ATGTATTATTATTATTATTATTATTATTAA",
                "GC-rich versus AT-rich panel effect size, CI, bootstrap, and coding-context controls",
            ),
            ("dna_analyzer", "ATGGCGGCGGCGGCGGCGGCGGCGGCGTAA", "Representative GC-rich DNA composition control"),
            ("dnabert2_analysis", "motifs:TATAATAAATTGACA", "DNABERT2-style motif positive-control calibration"),
            (
                "hypothesis_tester",
                "ttest:[0.833333,0.833333,0.766667,0.800000]:[0.033333,0.066667,0.066667,0.033333]",
                "Independent t-test on GC-fraction panels",
            ),
            ("protein_properties", "MKTAYIAKQRQISFVKSHFSRQLEERLGLIEVQ", "Protein property context control"),
        ],
    },
}


def _set_model_env(model: str | None) -> None:
    os.environ.setdefault("AMY_USE_LLM_ENHANCER", "1")
    os.environ.setdefault("AMY_USE_LLM_JUDGE", "1")
    os.environ.setdefault("AMY_USE_EVOLUTION", "1")
    if model:
        os.environ["AMY_ENHANCER_MODEL"] = model
        os.environ["AMY_RANKING_MODEL"] = model


def _hash_ok(experiment_id: str, base_dir: Path) -> bool:
    prov_path = base_dir / experiment_id / "provenance.json"
    output_path = base_dir / experiment_id / "output.txt"
    if not prov_path.exists() or not output_path.exists():
        return False
    try:
        record = json.loads(prov_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    expected = record.get("tool", {}).get("output_hash")
    actual = hashlib.sha256(output_path.read_text(encoding="utf-8").encode("utf-8")).hexdigest()
    return bool(expected) and expected == actual


async def _run_tool_plan(
    *,
    atlas: AtlasTools,
    provenance: ProvenanceManager,
    domain: str,
    calls: list[tuple[str, str, str]],
    timeout: float,
) -> tuple[list[dict], list[dict]]:
    successes: list[dict] = []
    failures: list[dict] = []

    for tool_name, tool_input, description in calls:
        print(f"tool: {tool_name} ({description})")
        started = time.monotonic()
        try:
            output = await asyncio.wait_for(
                atlas.run_scientific_tool(tool_name, tool_input, domain),
                timeout=timeout,
            )
        except Exception as exc:  # noqa: BLE001
            failures.append({
                "tool": tool_name,
                "input": tool_input,
                "description": description,
                "error": f"{type(exc).__name__}: {exc}",
            })
            print(f"  FAIL {type(exc).__name__}: {exc}")
            continue

        duration = time.monotonic() - started
        output_text = str(output)
        assessment = assess_tool_output(output_text, tool_name=tool_name)
        record = provenance.record_execution(
            tool_name=tool_name,
            tool_input=tool_input,
            tool_output=output_text,
            success=bool(assessment["usable"]),
            duration_seconds=duration,
            domain=domain,
            extra={"description": description, "assessment": assessment},
        )
        row = {
            "tool": tool_name,
            "tool_name": tool_name,
            "input": tool_input,
            "description": description,
            "result": output_text,
            "success": bool(assessment["usable"]),
            "duration_seconds": round(duration, 3),
            "experiment_id": record["experiment_id"],
            "provenance_path": provenance.get_provenance_path(record["experiment_id"]),
            "assessment": assessment,
        }
        if assessment["usable"]:
            successes.append(row)
            print(f"  OK {duration:.1f}s provenance={record['experiment_id']}")
        else:
            failures.append(row)
            print(f"  UNUSABLE markers={assessment['markers']}")

    return successes, failures


def _build_sections(domain: str, topic: str, tool_results: list[dict]) -> list[dict]:
    result_lines = []
    for result in tool_results:
        preview = str(result["result"])[:2400]
        result_lines.append(
            "\n".join(
                [
                    f"### {result['description']}",
                    f"**Tool:** `{result['tool']}`",
                    f"**Input:** `{result['input']}`",
                    f"**Experiment:** `{result['experiment_id']}`",
                    "",
                    "```text",
                    preview,
                    "```",
                ]
            )
        )

    return [
        {
            "heading": "Introduction",
            "content": (
                f"This validation run tests whether A.M.Y can produce an auditable "
                f"{domain} paper from real Atlas tool calls about {topic}."
            ),
        },
        {
            "heading": "Methods",
            "content": (
                "The runner executed a fixed domain plan through AtlasTools, recorded "
                "SHA-256 provenance for each usable output, and generated the manuscript "
                "through PaperGenerator with the same enhancer path used by A.M.Y."
            ),
        },
        {"heading": "Results", "content": "\n\n".join(result_lines)},
        {
            "heading": "Discussion",
            "content": (
                "The Discussion is intentionally replaced by PaperEnhancer when the "
                "enhancer is enabled. If the LLM path is unavailable, the deterministic "
                "domain-aware fallback is used."
            ),
        },
        {
            "heading": "Conclusion",
            "content": (
                "This run is a production-path validation artifact, not an external "
                "peer-reviewed scientific claim."
            ),
        },
    ]


async def run_validation(args: argparse.Namespace) -> int:
    if args.domain not in DOMAIN_PLANS:
        raise SystemExit(f"unknown domain {args.domain!r}; use --list")

    _set_model_env(args.model)

    plan = DOMAIN_PLANS[args.domain]
    calls = plan["calls"][: args.max_calls] if args.max_calls else plan["calls"]
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    print(f"E2E validation domain={args.domain} model={args.model or '(config/default)'} calls={len(calls)}")

    atlas = AtlasTools()
    provenance = ProvenanceManager()
    started = time.monotonic()
    tool_results, failed_results = await _run_tool_plan(
        atlas=atlas,
        provenance=provenance,
        domain=args.domain,
        calls=calls,
        timeout=args.tool_timeout,
    )
    await atlas.close()

    experiment_ids = [r["experiment_id"] for r in tool_results]
    if len(tool_results) < args.min_successes:
        summary = {
            "ok": False,
            "reason": f"only {len(tool_results)} usable tool calls; need {args.min_successes}",
            "domain": args.domain,
            "model": args.model,
            "tool_results": tool_results,
            "failed_results": failed_results,
        }
        out_path = OUT_DIR / f"e2e_{args.domain}_{run_id}.json"
        out_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
        print(out_path)
        return 1

    title = f"E2E Validation: {plan['topic']}"
    abstract = (
        f"A.M.Y production validation for {args.domain}: {len(tool_results)} usable "
        "Atlas tool outputs were recorded with provenance and synthesized into a paper."
    )
    generator = PaperGenerator(enhance=not args.no_enhance, output_dir=PAPERS_DIR)
    paper = await asyncio.wait_for(
        generator.generate_paper(
            title=title,
            abstract=abstract,
            sections=_build_sections(args.domain, plan["topic"], tool_results),
            references=None,
            knowledge_facts=[
                {"subject": args.domain, "predicate": "validated_topic", "object": plan["topic"], "confidence": 0.9}
            ],
            experiment_ids=experiment_ids,
            domain=args.domain,
            tool_results=tool_results,
        ),
        timeout=args.paper_timeout,
    )

    md_path = Path(paper["markdown_path"])
    md_text = md_path.read_text(encoding="utf-8") if md_path.exists() else ""
    reflection = reflect(md_text).to_dict() if md_text else None
    rubric = None
    discussion = None
    if md_path.exists() and score_paper is not None:
        scored = score_paper(md_path, peer_abstracts=[])
        rubric = {
            "total": scored.total,
            "per_dim": {
                name: getattr(scored, name)
                for name in [
                    "provenance_integrity",
                    "tool_diversity",
                    "falsifiability",
                    "explicit_limitations",
                    "numerical_claims_grounded",
                    "citation_accuracy",
                    "abstract_uniqueness",
                    "statistical_rigor",
                    "reproducibility_info",
                ]
            },
        }
    if md_path.exists() and score_discussion is not None:
        disc = score_discussion(md_path)
        discussion = {
            "total": disc.total,
            "word_count": disc.word_count,
            "claim_grounding": disc.claim_grounding,
            "limitation_cover": disc.limitation_cover,
            "alternatives": disc.alternatives,
            "calibration": disc.calibration,
            "reasoning_depth": disc.reasoning_depth,
        }

    provenance_hash_ok = {
        eid: _hash_ok(eid, provenance.base_dir)
        for eid in experiment_ids
    }
    summary = {
        "ok": paper.get("publication_status") == "published" and all(provenance_hash_ok.values()),
        "domain": args.domain,
        "model": args.model,
        "duration_seconds": round(time.monotonic() - started, 3),
        "env_flags": {
            "AMY_USE_LLM_ENHANCER": os.getenv("AMY_USE_LLM_ENHANCER"),
            "AMY_USE_LLM_JUDGE": os.getenv("AMY_USE_LLM_JUDGE"),
            "AMY_USE_EVOLUTION": os.getenv("AMY_USE_EVOLUTION"),
            "AMY_ENHANCER_MODEL": os.getenv("AMY_ENHANCER_MODEL"),
            "AMY_RANKING_MODEL": os.getenv("AMY_RANKING_MODEL"),
        },
        "tool_results": tool_results,
        "failed_results": failed_results,
        "experiment_ids": experiment_ids,
        "provenance_hash_ok": provenance_hash_ok,
        "paper": paper,
        "reflection": reflection,
        "rubric": rubric,
        "discussion": discussion,
    }

    out_path = OUT_DIR / f"e2e_{args.domain}_{run_id}.json"
    out_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"paper: {paper.get('markdown_path')}")
    print(f"rubric: {rubric['total'] if rubric else 'n/a'}")
    print(f"discussion: {discussion['total'] if discussion else 'n/a'}")
    print(out_path)
    return 0 if summary["ok"] else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--domain", default="mathematics")
    parser.add_argument("--model", default=None, help="Override Ollama model for enhancer/ranking judge")
    parser.add_argument("--list", action="store_true", help="List supported domains")
    parser.add_argument("--max-calls", type=int, default=None)
    parser.add_argument("--min-successes", type=int, default=2)
    parser.add_argument("--tool-timeout", type=float, default=180.0)
    parser.add_argument("--paper-timeout", type=float, default=240.0)
    parser.add_argument("--no-enhance", action="store_true", help="Disable PaperEnhancer/LLM paper enhancement")
    args = parser.parse_args()

    if args.list:
        for domain in sorted(DOMAIN_PLANS):
            print(domain)
        return 0
    return asyncio.run(run_validation(args))


if __name__ == "__main__":
    raise SystemExit(main())
