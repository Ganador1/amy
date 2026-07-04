# Chemistry SSH Novelty Design

## Goal

Advance the chemistry E2E branch from a known-control polyene gap verification into a focused identifiability study: given finite HOMO-LUMO gap observations from a polyene-like chain, determine whether the data support uniform finite-size closure, Peierls/SSH bond alternation, or boundary-state contamination.

## Scope

The implementation stays inside the existing Atlas chemistry tool surface and E2E harness. It adds one deterministic tool, updates the chemistry plan to call it, and generates a new chemistry paper. It does not claim a DFT discovery, a new material, or an experimental result.

## Scientific Claim Standard

A result can be labeled `candidate_novelty` only if it reports a falsifiable identifiability boundary that was not present in the prior paper, such as a finite-length regime where two SSH parameterizations are indistinguishable by gap-only evidence, or where boundary orientation creates mid-gap states that would mislead a naive Peierls-gap estimate.

Known results, including uniform Hückel gap closure and Peierls gap opening, remain labeled as controls.

## Architecture

- `atlas/app/run_agent_with_tools_legacy.py` receives a new `ssh_polyene_gap_map` tool.
- `scripts/run/run_e2e_validation.py` updates the chemistry plan to use the new map as the primary experiment, with existing Hückel, bond-alternated, and PySCF controls retained.
- Tests in `tests/test_atlas_tools_end_to_end.py`, `tests/test_production_harnesses.py`, and `tests/test_scientific_hardening.py` pin the public tool contract and paper-harness behavior.

## Tool Contract

Input format:

```text
4,6,8,10,12,16,20,40,80;deltas=0,0.05,0.1,0.2,0.4;orientations=trivial,topological;beta=-2.5
```

Output must include:

- A finite SSH/polyene gap map with chain lengths, dimerization deltas, and boundary orientations.
- Uniform baseline at `delta=0`.
- Peierls expected bulk gap `4*abs(beta)*delta`.
- Finite-chain measured gap for each condition.
- Edge-state warning when topological orientation produces a much smaller frontier gap than the bulk Peierls estimate.
- An identifiability summary that reports the smallest tested length where each nonzero delta is separable from the uniform baseline by a fixed threshold.

## Testing

The first failing tests must prove:

- `ssh_polyene_gap_map` is registered and callable.
- The output contains `identifiability_threshold_eV`, `orientation=topological`, `edge_state_warning`, and `smallest_identifiable_n`.
- The chemistry E2E plan includes `ssh_polyene_gap_map` and still retains existing controls.

## Expected Paper Improvement

The new paper should be stronger because it asks a sharper question than the previous branch: not "does bond alternation open a gap?" but "when can finite gap-only evidence distinguish Peierls physics from finite-size and edge-state alternatives?"
