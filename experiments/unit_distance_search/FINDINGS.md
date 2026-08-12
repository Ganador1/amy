# A.M.Y finite unit-distance replication and search

**Run date:** 2026-08-11<br>
**Status:** exact finite computational result; not a new asymptotic theorem<br>
**Provenance ID:** `mathematics_unit_distance_search_v1`<br>
**Canonical result SHA-256:** `b766dae6dc475aa96102089ecb7e94603c2b4f9be69928b35a3f236cf0a5ba1b`

## Outcome

A.M.Y reproduced the rescaled integer-grid mechanism behind the classical
lower bound for the planar unit-distance problem and then searched a strictly
larger family of irregular lattice subsets. All winning edge counts were
recomputed by a separate quadratic-time verifier using exact integer squared
distances.

| Points | Axis grid | Best complete square | Best greedy | Best evolved | Gain vs complete square | Avg. degree |
|---:|---:|---:|---:|---:|---:|---:|
| 64 | 112 | 168 (d²=5) | 192 | 196 (d²=170) | 16.67% | 6.125 |
| 100 | 180 | 288 (d²=5) | 319 | 333 (d²=130) | 15.62% | 6.660 |
| 144 | 264 | 456 (d²=25) | 494 | 509 (d²=65) | 11.62% | 7.069 |

The preregistered success condition was a positive gain over the best complete
square grid for every tested size. Result:
`all_improve_arithmetic_square=true` and
`all_exactly_verified=true`.

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
