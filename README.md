# A.M.Y

> An artificial mind that never sleeps. Thinks, researches, experiments, learns, and evolves autonomously.

**[Science Manifesto](SCIENCE_MANIFESTO.md)** · **[Atlas Tool Guide](ATLAS_TOOL_GUIDE.md)** · **[Detector Characterization](docs/DETECTOR_CHARACTERIZATION.md)** · **[Changelog](CHANGELOG.md)** · **[Use Policy](USE_POLICY.md)** · **[Security](SECURITY.md)** · **[Contributing](CONTRIBUTING.md)**

---

## Status (August 2026)

| Component | Status | Notes |
|---|---|---|
| Core (heartbeat, world model, workspace) | ✅ Functional | — |
| Cognition (reasoning, goals, curiosity, **Reflection**, **Ranking**, **Evolution**, **Meta-review**) | ✅ Functional | curiosity is an ICM/RND-inspired heuristic, not a trained net |
| Memory (episodic, semantic, procedural) | ✅ Functional | — |
| Sandbox (isolated execution) | ✅ Functional | — |
| **Atlas Tools (23 domains; 9 `evidence_grade='real_local'`, rest heuristic/tabulated/demo)** | ✅ Functional | real-library tools verified; see [Honest scope](#honest-scope-what-is-real-vs-heuristic) |
| Evolution (self-retrain belief-weight update + meta-review feedback) | ✅ Functional | both run in the live heartbeat: `_reflect` drives belief-weight recalibration on a throttle, and meta-review feedback from paper reviews is fed back into later reasoning prompts. Does not fine-tune a neural net on-device. |
| Senses (web, time, file, api) | ✅ Functional | — |
| Communication (paper generator + LLM enhancer + Reflection gate) | ✅ Functional | LLM enhancer/evolution opt-in via env flags |

**Multi-domain coverage:** Atlas domains produce papers end-to-end, with provenance integrity verified by SHA-256. The July 2026 E2E validation loop now has six focused scientific branches at target quality with `grounding_repair.repairs = 0`: astronomy, biology, chemistry, mathematics, physics, and statistics. New-pipeline papers (LLM enhancer + evolution) score meaningfully higher than prior versions on the project's own rubric and win a blind head-to-head against them 9/12 (a marginal result — 95% CI lower bound just under 0.5) — see [Quality](#paper-quality-vs-prior-versions).

---

## Vision

A.M.Y is not a chatbot. It is not an agent that waits for your question. It is an **autonomous artificial mind**: once given a research goal, it continuously investigates, reflects, experiments, retrains on its own findings, and only contacts you when there is something to report.

## Scientific foundations

| Pillar | Source | Role inside A.M.Y |
|---|---|---|
| **Active Inference (inspired-by)** | Karl Friston (Free Energy Principle) | Continuous perception-action loop that minimises a *surprise* signal. The surprise/prediction-error term is currently a **keyword-overlap heuristic** (`world_model._compare_prediction_to_reality`), not a learned generative model — Active-Inference-*inspired*, not a faithful free-energy implementation. |
| **Global Workspace Theory (inspired-by)** | Bernard Baars / Stanislas Dehaene | Attention bus: modules submit bids and the highest-utility one wins and is broadcast. Scoring is a priority + novelty + type-bonus **heuristic**, not a deep consciousness model. |
| **SOAR Cognitive Architecture** | Laird, Newell, Rosenbloom | Operative cycle: propose → evaluate → execute. Recursive substates. Chunking. |
| **Curiosity-Driven Learning** | Pathak et al. (ICM / RND) | Intrinsic motivation: when no extrinsic progress, curiosity drives exploration. |
| **Voyager** | Wang et al. 2023 (NVIDIA/Caltech) | Skill library + automatic curriculum + self-verification. |
| **NELL** | Tom Mitchell et al. (CMU) | 24 / 7 continual learning with a growing knowledge base. |
| **Sakana AI Scientist v2** | arXiv:2504.08066 | End-to-end paper generation with internal reviewing. |
| **Google AI Co-Scientist** | DeepMind 2025 | Multi-agent reflection + Elo tournament for hypothesis ranking. |
| **Human-AI Science Case Studies** | arXiv:2511.16072 | Human-AI collaboration patterns documented as case studies. |

## What A.M.Y can produce (today)

- **Real scientific tool calls.** A registry of scientific tools across 23 domains, of which **9 carry the static tag `evidence_grade='real_local'`** (`atlas/app/extended_science_tools.py`) — genuine library calls whose numbers are reproducible: **AstroPy** (`astropy_constants`, `astropy_unit_convert`, `astropy_cosmology`, `astropy_blackbody`), **PySCF** (`pyscf_hf_energy`, `pyscf_dft_energy`), **ASE** (`ase_optimize`, `ase_thermochemistry`), and **PyMatGen** (`pymatgen_structure`). Other real libraries — **SymPy** and **NumPy/SciPy** — are not statically tagged but are promoted to real-evidence grade *at runtime* by `tool_evidence_orchestrator.py` when they actually execute; **RDKit**, **BioPython**, and **Z3** run real library code through the chemistry/biology/math tools but likewise are not part of the static `real_local` set. The remainder are heuristic, tabulated, or demo tools — see [Honest scope](#honest-scope-what-is-real-vs-heuristic) for exactly which is which.
- **End-to-end papers** with sections, hypotheses, citations, SHA-256 provenance, and an automatic Self-Review block produced by the **Reflection Agent** — a deterministic structural-conformity checklist (Sakana / Co-Scientist *structure*, not an independent LLM peer review). It checks the draft has the expected parts (grounded numbers, stated limitations, falsifiable predictions), not that the science is correct.
- **LLM-written Discussion grounded in provenance.** With `AMY_USE_LLM_ENHANCER=1`, the Discussion and Implications are generated by the connected LLM conditioned on the *actual* tool outputs (the same strings hashed into `provenance.json`) — A.M.Y's implementation of the Sakana AI Scientist v2 manuscript write-up step (arXiv:2504.08066). The model is instructed to discuss only numbers present in the evidence, and the downstream `NumericVerifier` flags clinical-style statistics (p-values, HR/OR/RR with CI, median survival, clinical-context percentages) that lack nearby provenance — it pattern-matches those claims and checks that an `experiment_` id or dataset URL appears in their local context, rather than recomputing every figure (it does not re-derive HF energies, cosmological distances, or prime gaps). A deterministic domain-aware template path remains the default and the fallback when no LLM is reachable. (See [Honest scope](#honest-scope-what-is-real-vs-heuristic).)
- **Hypothesis ranking via Elo tournament + Evolution.** Hypotheses are ranked in a pairwise Elo tournament before the paper foregrounds any claim (Google Co-Scientist pattern, arXiv:2502.18864; new entrants start at Elo 1200 as in the paper). With `AMY_USE_LLM_JUDGE=1` the judge runs a pairwise *scientific debate* on novelty/correctness/testability; with `AMY_USE_EVOLUTION=1` the **Evolution agent** refines the top hypotheses (the paper's iterative-improvement engine). In a blind, independently-LLM-judged head-to-head this engine produced measurably better hypotheses than no-learning and a pool-dynamics placebo (see [`experiments/learning_ablation/FINDINGS.md`](experiments/learning_ablation/FINDINGS.md)).
- **Reproducibility per paper.** Every tool invocation gets a [`data/experiments/<id>/provenance.json`](data/experiments) file with input, output preview, SHA-256 of full output, and full environment record.
- **Verified finite mathematical search.** The unit-distance experiment combines exact integer certificates with greedy and seeded evolutionary search. On 64, 100, and 144 points it improves the best complete-square arithmetic-grid control by 16.67%, 15.62%, and 11.62%, respectively. These are finite lower-bound constructions, not a reproof of OpenAI's 2026 asymptotic theorem or a certified global record. See the [findings and claim boundary](experiments/unit_distance_search/FINDINGS.md).
- **Exact frontier-result replication.** A.M.Y independently expands the 2026 Alpöge-Fable polynomial map, verifies `det(JF) = -2`, and checks two disjoint rational three-point collisions. This reproduces the published dimension-three Jacobian counterexample with exact SymPy arithmetic; it is not a discovery claim or a resolution of the remaining plane case. See the [exact audit](experiments/jacobian_counterexample/FINDINGS.md).
- **Explicit detector uncertainty.** Publication gates carry source digests, but source identity is not treated as measured capability. Until a digest-bound benchmark supplies class definitions, a confusion matrix, sensitivity/specificity with confidence intervals, scope, limitations, and evidence provenance, the gate is recorded as `unmeasured`; generated artifacts require manual review and are not eligible for automatic external release. Producer-declared assurance never counts as independent verification: safety or release policy requires separately verified, authorized, digest-bound evidence plus claim semantics bound to the measured positive class and passing rule. See the [detector characterization contract](docs/DETECTOR_CHARACTERIZATION.md).

## Recent verified mathematics experiments (August 2026)

A.M.Y replicated the rescaled integer-grid mechanism underlying classical lower bounds for the planar unit-distance problem, then searched a larger family of irregular lattice subsets. The baseline exhaustively selects the best distance for a complete square grid; each evolved winner is independently recounted in `O(n²)` using exact integer squared distances. A second clean run reproduced the same canonical SHA-256 (`b766dae6dc475aa96102089ecb7e94603c2b4f9be69928b35a3f236cf0a5ba1b`).

| Points | Best complete square | A.M.Y evolved | Relative gain |
|---:|---:|---:|---:|
| 64 | 168 | **196** | **16.67%** |
| 100 | 288 | **333** | **15.62%** |
| 144 | 456 | **509** | **11.62%** |

The result is deliberately finite: it does not reproduce the class-field-tower argument, claim an asymptotic exponent, or certify that these are the best published configurations. The executable search, point certificates, controls, provenance metadata, and full limitations are in [`experiments/unit_distance_search/`](experiments/unit_distance_search/).

The same replication program also audited the July 2026 Alpöge-Fable counterexample to the Jacobian conjecture in dimension three. Exact symbolic expansion returned `det(JF) = -2`, while two independent rational certificates each mapped three distinct inputs to one output. A clean rerun reproduced canonical SHA-256 `5033cd69a655fa2f2ee010505efc9c5d5b56c630cc3e5fd35c8ba0280626bbe0`; see [`experiments/jacobian_counterexample/`](experiments/jacobian_counterexample/). This is verification of a published map, not a new counterexample.

## Recent benchmark

23 papers, one per Atlas domain, generated in ~7 minutes:

| Metric | Value |
|---|---:|
| Average rubric score | **71.00 / 100** |
| Average reflection score (structural conformity) | **100 / 100** |
| Verdict tally | **STRONG = 2 · GOOD = 21 · WEAK = 0** |
| Highest-scoring paper | 80.45 (Prime Counting and Twin Prime Density) |
| Lowest-scoring paper | 62.42 (AM Process Configuration) |

> The reflection score is a **deterministic structural-conformity check**, not a quality grade or independent peer review. It verifies the draft satisfies a fixed six-item format checklist (numbers traceable to provenance, a limitations sentence, a Testable-Predictions block, etc.); the paper generator inserts boilerplate that satisfies the same regexes, so the 100/100 is uniform across the batch even where rubric novelty is 0. Read it as "the template was filled in correctly," not "the science is sound."

See [`experiments/all_domains/REVIEW.json`](experiments/all_domains/REVIEW.json) for the full breakdown and [`experiments/flagship/papers/`](experiments/flagship/papers/) for a deep-dive paper modelled on the arXiv:2511.16072 case-study format (rubric 71, reflection 100, 14 verifiable tool calls).

## Recent E2E branch validation (July 2026)

The latest focused E2E loop uses the same production harness under either GLM-5.2/Ollama or the deterministic fallback, depending on available credentials. Instead of broad exploration, each branch is forced into a single falsifiable scientific contract: baseline, perturbation/alternative, independent control, explicit limitations, and provenance-grounded numerical claims. The loop controller is [`scripts/run/branch_quality.py`](scripts/run/branch_quality.py); the production harness is [`scripts/run/run_e2e_validation.py`](scripts/run/run_e2e_validation.py).

| Domain | Scientific target | Rubric | Discussion | Grounding repairs | Artifact |
|---|---|---:|---:|---:|---|
| Astronomy | Planck18 luminosity-distance residuals vs low-z Hubble-law controls | **98.0** | 83.075 | 0 | [`e2e_astronomy_20260703_171209.json`](experiments/e2e_validation/e2e_astronomy_20260703_171209.json) |
| Biology | GC-rich vs AT-rich sequence panels with coding-context controls | **100.0** | 86.611 | 0 | [`e2e_biology_20260703_165642.json`](experiments/e2e_validation/e2e_biology_20260703_165642.json) |
| Chemistry | SSH polyene finite-chain identifiability with eigenvector edge-localization controls | **100.0** | 80.530 | 0 | [`e2e_chemistry_20260704_150913.json`](experiments/e2e_validation/e2e_chemistry_20260704_150913.json) |
| Mathematics | Prime-gap scaling against logarithmic and Cramer-style baselines | **97.5** | 84.370 | 0 | [`e2e_mathematics_20260703_012240.json`](experiments/e2e_validation/e2e_mathematics_20260703_012240.json) |
| Physics | Hydrogen Rydberg inverse-square scaling against perturbation controls | **93.5** | 81.023 | 0 | [`e2e_physics_20260703_163343.json`](experiments/e2e_validation/e2e_physics_20260703_163343.json) |
| Statistics | Two-sample inference with effect size and uncertainty controls | **100.0** | 84.241 | 0 | [`e2e_statistics_20260703_164519.json`](experiments/e2e_validation/e2e_statistics_20260703_164519.json) |

The important change is not just the higher scores. Earlier failures were mostly caused by broad branch objectives, missing competing models, and LLM Discussion sections that introduced unsupported numbers. The new branch loop adds deterministic tools such as `cosmology_residual_comparison`, `gc_at_panel_comparison`, `two_sample_effect_power`, `rydberg_scaling_comparison`, `ssh_polyene_gap_map`, `ssh_edge_localization_map`, and explicit model-comparison controls, then filters unsupported evolved hypotheses before the paper is written. In chemistry, the final pass now tests frontier-pair edge weight, inverse participation ratio, and participation-site localization directly instead of relying on gap-only SSH inference. In the final branch-quality pass, all six domains report `status=target`, `reflection.score=100`, and zero failed tool calls.

## How A.M.Y thinks — the cognitive cycle in depth

A.M.Y is built around a continuous **heartbeat loop**. The loop never returns; it is the loop, not an `if __name__` block, that defines the agent. Each tick of the loop runs the same five-phase cognitive cycle inspired by SOAR, Active Inference, and Global Workspace Theory.

### The five phases of one heartbeat

1. **PERCEIVE** — `senses/` modules read the world. `web_sensor.py` pulls fresh literature (arXiv, PubMed-style sources). `time_sensor.py` advances the clock. `file_sensor.py` watches local data. `api_sensor.py` polls APIs the user wired in. The new perceptions are reduced to surprise signals against the current world model.

2. **ATTEND** — `core/global_workspace.py` runs the attention bus. Every cognitive module (curiosity, goal stack, memory recall, reflection) submits a bid for the workspace. The highest-utility bid wins the tick and gets broadcast to all modules. This is the explicit implementation of Bernard Baars' Global Workspace Theory: only one thought is "conscious" at a time, but every subsystem hears it.

3. **THINK** — `cognition/reasoning.py` runs a recursive chain over the winning workspace content. For a typical research tick this means: form a hypothesis, decompose it into testable predictions, identify which Atlas tools could falsify each prediction, plan the call sequence. `cognition/curiosity.py` (ICM / RND) injects an intrinsic reward signal proportional to expected information gain, so dull tool calls are deprioritised even when they would succeed.

4. **ACT** — A.M.Y picks the best plan and executes it. Scientific tool calls go through `core/atlas_tools.py`, which speaks JSON to a persistent Atlas worker (see Atlas section below). Code experiments go through `sandbox/executor.py`, which validates syntax and resource limits before running. Results flow back into memory and into the next perception.

5. **LEARN** — `memory/episodic.py` records what happened. `memory/semantic.py` updates the knowledge graph. The reflection pass runs `memory/consolidation.py` to chunk successful experiments into procedural skills (Voyager-style) and extract recurring themes. `evolution/curriculum.py` decides what to study next. `evolution/self_retrain.py` runs **in the live heartbeat** (driven by `_reflect` on a throttle) and improves A.M.Y in two ways: (a) a **belief-weight recalibration** — it nudges each world-model belief's confidence toward its empirical reliability (confirm/contradict ratio) with a fixed scalar moving average and persists the new values to the knowledge graph; this is a heuristic recalibration (not a full Bayesian or neural-net update), and the project's own ablation measured **no downstream effect**, so it is kept for transparency rather than as a quality lever; and (b) **meta-review feedback propagation** via `cognition/meta_review_agent.py`, the Google Co-Scientist Meta-review mechanism that synthesizes recurring weaknesses from prior reviews and feeds them into the next cycle's prompts — this is the path that actually changes later outputs. (The Co-Scientist paper notes this kind of feedback loop "enables learning without back-propagation"; A.M.Y does **not** fine-tune a large neural network on-device.)

The loop then returns to PERCEIVE. There is no exit condition. The loop runs until the OS kills it.

### Observability — what the loop is doing, without grepping logs

Because A.M.Y is meant to run unattended, the heartbeat keeps a live metrics surface (`core/metrics.py`, `HeartbeatMetrics`): cycles, errors and error rate, action mix, experiment success rate, papers, reflections, consolidations, a rolling mean cycle time, and RSS. `heartbeat.status_snapshot()` merges those counters with the current cognitive state (cycle, focus, goal, interval) into one JSON-serializable dict, and a `heartbeat.status` line is logged at every reflection checkpoint. A representative live snapshot:

```
heartbeat.status  cycles=2  errors=0  error_rate=0.0  avg_cycle_seconds=24.5
  actions={'experiment': 2, 'think_more': 1}
  experiments={'succeeded': 1, 'failed': 1, 'success_rate': 0.5}
  reflections=1  consolidations=0  rss_mb=67.0  uptime_seconds=71.1
```

**The "never sleeps / runs indefinitely" claim is empirically tested**, not just asserted: a real 60-minute, no-goal, curiosity-only run ([`experiments/e2e_v2/LONGEVITY_FINDINGS.md`](experiments/e2e_v2/LONGEVITY_FINDINGS.md)) reached 90 cycles with memory bounded in a stable ~56–75 MB band (ending *below* where it started), zero uncaught cycle errors, and graceful recovery from transient API rate-limits — the bounded buffers + per-cycle `try/except` are the mechanism, the flat memory curve is the proof.

## The multi-agent components

A.M.Y introduces three cognitive agents inspired by the published architectures of Sakana AI Scientist v2 and Google DeepMind's AI Co-Scientist: the **Ranking Agent** (Elo tournament), the **Reflection Agent** (self-review gate), and the **Meta-review Agent** (feedback propagation across cycles). All are pure-Python, no external services required, and falsifiable through tests.

### Ranking Agent — Elo tournament over hypotheses

When the paper enhancer generates N candidate hypotheses, A.M.Y does not pick the first plausible one. Instead it runs a round-robin pairwise tournament:

```python
from cognition.ranking_agent import run_tournament

candidates = [
    {"hypothesis": "Bond energies follow electronegativity scaling",
     "novelty_status": "known_control", "confidence": 0.85},
    {"hypothesis": "PySCF HF/sto-3g HOMO-LUMO gap of H2 is within 5% of literature",
     "novelty_status": "candidate_novelty", "confidence": 0.70},
    # ... more
]
ranked = run_tournament(candidates, rounds=2, seed=42)
top = ranked[0]   # highest-Elo hypothesis
```

Two judges are available:

- `heuristic_judge` — deterministic, no API calls. Scores each hypothesis on novelty status (40%), confidence (20%), specificity proxy (20%), and falsifiability markers like the words "test", "measure", "compare against" (20%). Then the pair's normalised scores become the Elo update.
- `llm_judge` — async pairwise call to an Ollama Cloud model. Opt in with `AMY_USE_LLM_JUDGE=1`. Override the model with `AMY_RANKING_MODEL=qwen3-next:80b` (or any model your cloud key can reach). Falls back to the heuristic on any error.

K-factor follows FIDE rules: 40 for the first 5 matches per record, 20 up to 15, then 10. This makes early matches matter more, which is what you want when N is small.

The top-K hypotheses get foregrounded in the manuscript with their Elo and tournament record, so readers can see *that* the ranking happened and *how* each candidate fared.

### Reflection Agent — structured self-review gate

Before a paper is finalised, `cognition/reflection_agent.py` runs a deterministic six-check rubric against the draft:

1. **Numerical-claim grounding.** Decimal numbers in the Discussion section (extracted by a `-?\d+\.\d+` regex) must trace to a `data/experiments/<id>/provenance.json` output; unsupported ones raise a `high` severity issue. This catches the common case but is **not** universal coverage — bare integers, scientific notation, and ratios written other ways can slip through. The separate `NumericVerifier` (used at save time) likewise targets only high-risk quantitative patterns (p-values, HR/OR/RR with CI, median survival, clinical-context percentages), not every number. Treat numeric grounding as **high-risk-claim detection plus provenance-gated experiment IDs**, not exhaustive verification.
2. **Explicit limitations.** The paper must say what it is *not* claiming. The agent looks for phrases like "does not claim", "calibration control", "without asserting novelty".
3. **Falsifiability of hypotheses.** Each `H<n>.` block must have an explicit test procedure. Phrases like "Testable via:", "measure", "compare against" satisfy this.
4. **Citation freshness.** Unverified citations (marked by the upstream `CitationVerifier`) lower the score.
5. **Statistical reporting.** If the manuscript touches statistics, it should mention p-values, confidence intervals, effect sizes, or n.
6. **Alternative explanations.** The Discussion should consider competing explanations, not only the favoured interpretation.

Issues are returned as `{severity, section, message, suggestion}`. The agent annotates the draft with a `## Self-Review (Reflection Agent)` block listing all medium and high issues, so peer reviewers (or the author) get an honest map of the paper's weak points. The agent is *advisory*: drafts are not rejected by the Reflection score alone (the `_prepublication_gate` already handles hard rejections), but the score and issues are persistent and visible.

### Meta-review Agent — feedback propagation across cycles

`cognition/meta_review_agent.py` implements the Google AI Co-Scientist Meta-review agent (arXiv:2502.18864, §3.3.6). It ingests the Reflection Agent's issues and the peer-review scores from every paper, classifies each issue into a stable pattern (ungrounded number, missing limitations, weak falsifiability, …), and surfaces the *recurring* weaknesses as actionable guidance:

```python
from cognition.meta_review_agent import MetaReviewAgent

agent = MetaReviewAgent()
agent.ingest_review(reflection_result)     # from the Reflection Agent
agent.ingest_peer_review(peer_review)      # from the PeerReviewer
digest = agent.synthesize()                # recurring issues + weak criteria + guidance
prompt_suffix = digest.as_prompt_suffix()  # appended to the next cycle's prompts
```

This is the paper's mechanism for "feedback propagation and learning *without* back-propagation": the synthesized critique is appended to downstream prompts so the next round of hypotheses and write-ups pre-empt the mistakes that kept recurring. `evolution/self_retrain.py` drives this loop and, separately, performs the belief-weight update described in the cognitive cycle's LEARN phase. **It is wired into the live `amy.py` heartbeat:** `_reflect` runs the belief-weight recalibration on a throttle (`reflections_per_retrain`), each written paper's review is fed in via `record_review`, and the synthesized recurring-weakness digest is rendered into the next reasoning prompt as a "Lessons From Prior Reviews" block.

## Atlas / AXIOM — the scientific platform underneath

A.M.Y does not call SymPy or PySCF directly. It speaks JSON over stdin / stdout to a persistent worker process that owns the entire AXIOM Atlas platform. This isolation is deliberate: it keeps the A.M.Y cognitive state separate from heavy scientific imports, lets Atlas use its dedicated Python 3.13 environment while A.M.Y runs on Python 3.13 or 3.14, and makes every Atlas call a structured request/response with explicit timeouts and error handling.

### What AXIOM Atlas is

AXIOM Atlas is a scientific research platform with three layers:

- **Tool registry** (`atlas/app/run_agent_with_tools_legacy.py`, `atlas/app/extended_science_tools.py`) — 100+ callable tools are discovered at runtime across 23 domains. Each tool has a `name`, `domain`, `description`, `input_format`, and a callable. Adding a new tool is one `register_tool(ToolDescriptor(...))` call.
- **Service layer** (`atlas/app/services/`, `atlas/app/domains/`) — services for heavier capabilities: GNoME materials discovery, additive manufacturing process configuration, gravitational lensing, light EEG band-power analysis, climate evidence orchestration, and more. **Maturity varies** — some are real, some heuristic, and a few (AlphaFold 3, ClinicalBERT in the `services/` path) are mock/keyword-only; see [Honest scope](#honest-scope-what-is-real-vs-heuristic) before relying on any service's numbers.
- **Safety kernel** (`atlas/app/security/`) — the misuse guard, the actor-tracking risk policy, and the safety wrapper that every tool call must pass through. Fails closed by design.

The full surface area (FastAPI app, multi-agent orchestrator, peer review pipeline, Lean 4 management, quantum computing experiments) lives in `atlas/` and can be used independently of A.M.Y; A.M.Y is one consumer among possible others.

### The tool registry, by domain

The registry exposes 100+ callable tools at runtime once dynamic registration (`_register_service_tools`, `evidence_corroborate_<domain>`) is included. Of these, **9 carry the static tag `evidence_grade='real_local'`** (the AstroPy, PySCF, ASE, and PyMatGen tools listed above — genuine, reproducible library calls); the rest are heuristic, tabulated, or demo. SymPy/SciPy run real code too and are promoted to real-evidence grade at runtime by `tool_evidence_orchestrator.py`, but are not part of the static tag set. To exercise the whole registry, run `scripts/diagnostics/test_all_94_tools.py`: it discovers the live tool list from the Atlas worker itself (and caches it to `data/diagnostics/worker_tools.json`), so it runs from a fresh clone with no author-specific setup. The counts below are the static registry by domain.

| Domain | Count | Notable tools |
|---|---:|---|
| Mathematics | 20 | `sympy_solve_equation`, `sympy_derivative`, `sympy_integrate`, `sympy_simplify`, `sympy_prime_analysis`, `prime_gap_analysis`, `number_theory_advanced`, `mathematical_discovery`, `conjecture_engine`, `automated_prover`, `z3_prover`, `z3_verify_theorem`, `graph_theory`, `topology_invariants`, `symbolic_calculus`, `calculus_engine` |
| Chemistry | 22 | `molecular_weight_calc`, `bond_energy_analyzer`, `molecular_orbital_energy`, `huckel_polyene_scaling`, `bond_alternated_polyene_scaling`, `ssh_polyene_gap_map`, `ssh_edge_localization_map`, `computational_chemistry`, `pyscf_hf_energy`, `pyscf_dft_energy`, `ase_optimize`, `ase_thermochemistry`, plus service-backed adapters |
| Physics | 13 | `quantum_energy_levels`, `rydberg_scaling_comparison`, `quantum_circuit`, `astropy_constants`, `astropy_blackbody`, `calculus_engine`, plus services for plasma physics, particle physics, solid-state physics, quantum physics, gravitational lensing, physics-informed neural networks |
| Biology | 8 | `dna_analyzer`, `gc_at_panel_comparison`, `sequence_analyzer`, `protein_properties`, `dnabert2_analysis`, plus services for genomics, computational biology, alphafold3 protein structure |
| Statistics | 6 | `numpy_statistics`, `numpy_distribution`, `numpy_correlation`, `correlation_analysis`, `hypothesis_tester`, `two_sample_effect_power` |
| Astronomy | 5 | `cosmology_residual_comparison`, `astropy_cosmology`, `astropy_blackbody`, plus astronomical ML and gravitational lensing services |
| Medicine | 4 | ClinicalBERT NER (keyword fallback in `services/`; real NER in `personalized/`), AlphaFold 3 (mock in `services/`; real in `personalized/`), advanced medical imaging, evidence corroboration |
| Materials | 3 | `gnome_materials`, `pymatgen_structure`, materials discovery service |
| Engineering | 3 | additive manufacturing, synthesis equipment, evidence corroboration |
| Neuroscience | 2 | light EEG band-power service, evidence corroboration |
| Number theory | 3 | `number_theory_advanced`, `prime_gap_model_comparison`, `prime_gap_hpc` |
| Materials science | 2 | `gnome_materials`, evidence corroboration |
| Research / meta | 3 | `literature_search`, `literature_verify_hypothesis_plus`, `validate_hypothesis` |
| Evidence corroboration | 15 | `evidence_corroborate_<domain>` for all 15 corroboration domains, each running a multi-tool orchestrator that mixes real, heuristic, and remote evidence sources |
| Other domain services | 4 | climate, drug discovery, energy storage, manufacturing, medical imaging, plasma physics, quantum computing, biomedical engineering, biophysics |

### The atlas_worker protocol

A.M.Y's `core/atlas_worker.py` is launched as a long-running subprocess. It speaks line-delimited JSON over stdin/stdout. Three actions are supported:

```
→ {"id": 1, "action": "ping"}
← {"id": 1, "result": "pong"}

→ {"id": 2, "action": "list_tools", "domain": "chemistry"}
← {"id": 2, "result": ["molecular_weight_calc", "pyscf_hf_energy", ...]}

→ {"id": 3, "action": "describe_tools", "domain": "chemistry"}
← {"id": 3, "result": [{"name": "pyscf_hf_energy", "domain": "chemistry",
                        "description": "...", "input_format": "..."}]}

→ {"id": 4, "action": "run_tool",
   "tool_name": "pyscf_hf_energy",
   "tool_input": "H 0 0 0; H 0 0 0.74"}
← {"id": 4, "result": "PySCF Hartree-Fock RHF result:\n  Total energy: -1.11675931 Ha..."}
```

Two design decisions matter here. First, `run_tool` redirects the worker's `sys.stdout` to an in-memory buffer during execution, so any tool that prints (Brian2, libsbml) cannot corrupt the JSON channel. Second, the safety kernel and the misuse guard are evaluated *before* the worker is even reached, so a blocked operation never starts up its dependencies.

### Provenance — what gets written every time a tool runs

For every successful tool invocation A.M.Y creates a directory under `data/experiments/<id>/`:

```
data/experiments/mathematics_prime_gap_analysis_20260521_155341_a1b2c30/
├── provenance.json
└── output.txt
```

`provenance.json` carries:

```json
{
  "experiment_id": "mathematics_prime_gap_analysis_20260521_155341_a1b2c30",
  "timestamp": "2026-05-21T15:53:41+00:00",
  "tool": {
    "name": "prime_gap_analysis",
    "input": "1000000",
    "output_hash": "<sha256 of output.txt>",
    "output_length": 263,
    "success": true,
    "duration_seconds": 8.41
  },
  "output_preview": "Prime gap analysis up to 1000000:\n  Number of primes: 78498...",
  "domain": "mathematics",
  "environment": {
    "python_version": "3.13.5",
    "platform": "Darwin",
    "machine": "arm64"
  }
}
```

`output.txt` carries the full tool output. The SHA-256 in `provenance.json` is the hash of `output.txt`. The rubric scorer recomputes that hash on every paper review and rejects manuscripts where the claimed hash does not match. This is what makes the system *honest*: a paper cannot make a numerical claim without a provenance file that resolves to a verifiable hash.

### Adding a new Atlas tool

If you want A.M.Y to use a new scientific library, the cycle is:

1. Add a wrapper function in `atlas/app/extended_science_tools.py` (or a new module).
2. Register a `ToolDescriptor` with `name`, `domain`, `description`, and `input_format`.
3. Restart the worker. A.M.Y picks up the new tool through `describe_tools` automatically.

The Atlas misuse guard runs against every input before the tool is reached, so new tools inherit the safety policy without writing any policy code.

## Showcase papers

The `papers/showcase/` directory contains the curated set of papers A.M.Y has produced. They illustrate what the pipeline does *today*, scored by the same deterministic rubric:

1. **`01_FLAGSHIP_prime_gaps_cramer.md`** — flagship deep-dive on the Cramér-Granville heuristic. 14 verifiable Atlas tool calls across four decades of N (10^3 to 10^6, plus the 10^7 audit that surfaced the original cap bug). Includes a derived Cramér-ratio table and a falsifiable prediction. Rubric 71, Reflection pass.
2. **`02_mathematics_prime_counting.md`** — top-ranked all-domain paper (rubric 80.45). Reproduces π(N), twin-prime density, and the 1000th prime across multiple decades, all with provenance.
3. **`03_quantum_computing_bell_state.md`** — Bell-state preparation as a NISQ hardware calibration control. Quantum circuit simulation plus literature grounding.
4. **`04_chemistry_cross_level.md`** — cross-level comparison of IUPAC tables, Hartree-Fock, B3LYP DFT, and EMT atomistic on the same small molecules.
5. **`05_astronomy_cosmology.md`** — Planck18 cosmological distances and stellar blackbody spectra. Generated entirely with AstroPy tools added in v1.0.
6. **`06_novelty_cramer_six_decades.md`** — the only paper in the current showcase with a measured novelty score of 30. The novelty signal comes from extending the Cramér ratio audit to N = 10^7, which became possible after the prime_gap_analysis cap bug was fixed during the all-domain run.

The full 23-domain batch lives in `experiments/all_domains/papers/` and is reproducible with `python experiments/all_domains/generate_all.py` followed by `generate_remaining.py`. The rubric scorer is at `experiments/ab_test/scoring/score_paper.py`.

## A/B and multi-model experiments

`experiments/` contains the full experimental harness used to validate every claim in this README:

- **`ab_test/`** — baseline vs improved rubric comparison. Reports +17.28 points on average (+34.8%) after wiring the Reflection and Ranking agents.
- **`all_domains/`** — one paper per Atlas domain (23 / 23 covered).
- **`flagship/`** — the flagship deep dive.
- **`multimodel/`** — same topic run across seven model configurations. In the original run the spread across models was small (50-52 rubric) because the enhancer was template-driven at the time and the model only affected ranking judgements when LLM-judge was on. The LLM-backed write-up (`AMY_USE_LLM_ENHANCER=1`) now makes the Discussion model-dependent; re-running this harness with the flag on is the intended way to measure whether the rubric rises and varies across models.
- **`novelty_hunt/`** — eight papers on diverse cross-scale topics designed to surface novelty signals.
- **`learning_ablation/`** — does adding belief-weight updates beat the Co-Scientist's feedback-only design? Across four escalating runs and five adversarial-verification panels (which rejected three flawed analyses before the valid instrument was found), the answer: belief-weight updates add nothing measurable, while the Evolution-agent engine produces genuinely better hypotheses in a blind head-to-head. Full write-up in [`experiments/learning_ablation/FINDINGS.md`](experiments/learning_ablation/FINDINGS.md).
- **`e2e_validation/`** — focused production-path branch validation. The latest GLM-5.2 run drives six scientific branches to target quality with zero grounding repairs, using the same `PaperGenerator`, Reflection gate, LLM enhancer, Ranking/Evolution path, and SHA-256 provenance used by A.M.Y.

Every harness emits a re-scoreable JSON. Nothing in this README is unverifiable from the repository.

## Paper quality vs prior versions

The upgraded pipeline (LLM enhancer + Evolution agent + working LLM judge) produces measurably better papers than earlier A.M.Y versions, validated end-to-end with real Atlas tool calls and adversarial verification (`experiments/e2e_v2/`):

- **Rubric.** Fresh papers across five domains score ~76–88 on the project's deterministic 9-dimension rubric (`experiments/ab_test/scoring/score_paper.py`), vs a prior-version baseline of ~71 (curated showcase) and ~40 (legacy flat corpus). Provenance integrity (SHA-256 re-hash) is intact on every audited paper.
- **Focused branch loop.** The July 2026 E2E branch loop now reaches target status across six domains: astronomy 98.0, biology 100.0, chemistry 100.0, mathematics 97.5, physics 93.5, and statistics 100.0. Every final branch has `grounding_repair.repairs = 0`, `reflection.score = 100`, and no failed tool calls.
- **Longitudinal corpus.** Scoring the historical paper corpus by era (`experiments/e2e_v2/mine_corpus.py`): the new pipeline roughly **doubles** the legacy mean rubric and **halves its variance**.
- **Blind head-to-head.** Under an independent LLM judge, the reproducible result (three byte-identical runs, 40-paper prior pool) is **9/12** wins for the new papers — win rate 0.75, 95% CI **[0.468, 0.911]**. The lower bound dips just below 0.5, so this is **marginal / not statistically significant at 95%**: it points the right way but does not clear the bar. One additional run with a different (42-paper) prior pool reached 10/12 (CI [0.552, 0.953], which would clear it); we report the dominant reproducible figure rather than the single most favorable run.

These figures measure pipeline quality on an internal rubric, **not** external peer review. The Discussion-grounding still depends on the LLM enhancer being enabled and reachable.
## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     A.M.Y COGNITIVE CORE                        │
│                                                                 │
│  ┌──────────┐  ┌──────────────┐  ┌───────────┐  ┌───────────┐ │
│  │PERCEPTION│  │  WORLD MODEL │  │ GOAL STACK│  │ CURIOSITY │ │
│  │ (senses) │→ │ (free energy)│← │ (SOAR)    │← │ (ICM/RND) │ │
│  └──────────┘  └──────────────┘  └───────────┘  └───────────┘ │
│        ↓              ↕                ↓               ↓       │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │            GLOBAL WORKSPACE  (attention bus)             │   │
│  │   Modules compete → winner broadcasts to all             │   │
│  └─────────────────────────────────────────────────────────┘   │
│        ↓              ↓                ↓               ↓       │
│  ┌──────────┐  ┌──────────────┐  ┌───────────┐  ┌───────────┐ │
│  │  SKILL   │  │  KNOWLEDGE   │  │ EXPERIMENT│  │  SELF-    │ │
│  │  LIBRARY │  │  GRAPH       │  │ ENGINE    │  │  RETRAIN  │ │
│  │  Voyager │  │  NELL-like   │  │ sandbox   │  │  loop     │ │
│  └──────────┘  └──────────────┘  └───────────┘  └───────────┘ │
│        ↓              ↓                ↓               ↓       │
│  ┌──────────┐  ┌──────────────┐  ┌───────────────────────────┐│
│  │ RANKING  │  │  REFLECTION  │  │  PAPER  GENERATOR         ││
│  │ AGENT    │  │  + META-     │  │  (Markdown + PDF + SHA)   ││
│  │ Elo 1200 │  │  REVIEW loop │  │  + LLM write-up + prov.   ││
│  └──────────┘  └──────────────┘  └───────────────────────────┘│
└─────────────────────────────────────────────────────────────────┘
                    ↕ HEARTBEAT LOOP (never stops)
```

## Repository layout

```
A.M.Y/
├── amy.py                       # Entry point — starts the heartbeat
├── pyproject.toml               # pip-installable
├── requirements.txt             # Pinned versions
├── pytest.ini                   # asyncio mode = auto
├── conftest.py                  # Test path + cwd fixture
├── ENVIRONMENT.md               # venv layout (root + atlas/.venv_new)
├── LICENSE                      # Apache-2.0
│
├── core/                        # Cognitive core: heartbeat, workspace, atlas bridge
│   ├── atlas_tools.py           # Async client to Atlas worker
│   ├── atlas_worker.py          # Persistent stdin/stdout JSON protocol
│   ├── global_workspace.py
│   └── ...
│
├── cognition/                   # Reasoning, goals, curiosity, reflection, ranking
│   ├── reasoning.py
│   ├── reflection_agent.py      # Sakana / Co-Scientist self-review
│   ├── ranking_agent.py         # Elo tournament (init 1200) + LLM debate judge
│   └── meta_review_agent.py     # Co-Scientist Meta-review feedback loop
│
├── memory/                      # episodic, semantic, procedural, consolidation
├── senses/                      # web, time, file, api sensors
├── skills/                      # Voyager-style skill library
├── communication/               # Paper generator + Reflection gate
├── sandbox/                     # Isolated experiment execution
├── evolution/                   # Curriculum + self-retrain
│
├── atlas/                       # Dynamic registry (105 tools in current check), 23 domains
│   ├── app/extended_science_tools.py  # NEW — AstroPy/PySCF/ASE/PyMatGen
│   ├── app/run_agent_with_tools_legacy.py
│   └── ...
│
├── tests/                       # 56+ test files; fast hermetic lane runs in CI
├── scripts/                     # run/, diagnostics/, analysis/
├── experiments/                 # all_domains/, flagship/, ab_test/, multimodel/
├── papers/                      # Generated papers (Markdown + PDF)
└── data/experiments/            # Provenance JSON + raw output per tool call
```

## Quick start

```bash
# 1. Set up environments (see ENVIRONMENT.md for the full layout)
# A.M.Y supports Python 3.13 and 3.14. Atlas uses a separate 3.13 venv because
# parts of its scientific stack do not support 3.14 yet.
python3.13 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/pip install -e .

# 2. Build the dedicated Atlas environment
python3.13 -m venv atlas/.venv_new
atlas/.venv_new/bin/pip install -r atlas/requirements.txt

# 3. Add your Ollama Cloud key
cp .env.example .env
# edit .env with OLLAMA_CLOUD_API_KEY=...

# 4. Build the fail-closed experiment sandbox configured in config.yaml
docker build -t amy-sandbox:latest sandbox/

# 5. Run the cognitive loop with a goal
.venv/bin/python amy.py --goal "Investigate prime-gap statistics across decades"

# 6. Or generate a one-shot paper batch
.venv/bin/python experiments/all_domains/generate_all.py
.venv/bin/python experiments/all_domains/generate_remaining.py

# 7. Score the papers
.venv/bin/python experiments/all_domains/review_all.py
```

The wheel contains the A.M.Y core, not the embedded Atlas source tree or its
separate environment. Full scientific-tool operation therefore requires a
source checkout (as above), or explicit `AMY_ATLAS_ROOT` and
`AMY_ATLAS_PYTHON` paths to an Atlas installation.

The default wheel dependency set is intentionally lean. Optional extras are
available as `amy[memory]`, `amy[analysis]`, `amy[research]`, and `amy[ml]`;
`amy[full]` installs all of them. The source-checkout command above uses the
fully pinned `requirements.txt` for reproducible development.

## Configuration knobs

| Env var | Effect |
|---|---|
| `OLLAMA_CLOUD_API_KEY` | Required. Primary Ollama Cloud key. |
| `OLLAMA_CLOUD_API_KEY_2` | Optional failover key. |
| `AMY_USE_LLM_JUDGE=1` | Use LLM-backed pairwise judge (scientific-debate prompt) in the Ranking Agent (default: deterministic heuristic). |
| `AMY_RANKING_MODEL` | Override the model the LLM judge uses (e.g. `qwen3-next:80b`). |
| `AMY_USE_LLM_ENHANCER=1` | Generate the paper Discussion with the LLM, grounded in real tool outputs + provenance (default: deterministic template). Falls back to the template if no model is reachable. |
| `AMY_ENHANCER_MODEL` | Override the model used for the LLM Discussion write-up (defaults to `llm.reasoner` in `config.yaml`). |
| `AMY_USE_LLM_METAREVIEW=1` | Allow the Meta-review agent to phrase its synthesized feedback via the LLM (content is still derived from real accumulated reviews). |
| `AMY_ATLAS_ROOT` | Override the Atlas source-tree path. |
| `AMY_ATLAS_PYTHON` | Override the dedicated Atlas interpreter path. |
| `AMY_ATLAS_BRIDGE_TIMEOUT_SECONDS` | Override the full peer-review subprocess deadline. |
| `AMY_ATLAS_MODEL` | Override the model used by the Atlas peer-review bridge. |
| `ATLAS_ACTOR_ID` | Identity logged by Atlas misuse guard. |
| `MPLBACKEND=Agg` | Forced by the worker for headless plotting. |

### Mission-scoped memory

`config.yaml` enables `memory.namespace_by_mission`. A stable slug plus hash of
the mission goal selects `data/missions/<namespace>/`, isolating the knowledge
graph, episodic log, vector store, and procedural memory from unrelated runs.
Set an explicit `memory.mission_namespace` to keep several differently worded
goals in one research campaign. Existing legacy files under `data/` are left
untouched; set `namespace_by_mission: false` only when you intentionally want
that shared legacy state.

## Design philosophy

1. **Never sleeps.** The heartbeat loop runs indefinitely. With no urgent task, it reflects, consolidates memory, or explores out of curiosity.
2. **Recursive by nature.** Every finding spawns new questions. Every question spawns sub-goals.
3. **Doesn't need you.** It only contacts you when it discovers something significant.
4. **Learns for real.** It does not only accumulate text. It propagates synthesized review feedback into later cycles (the Co-Scientist Meta-review loop) and refines hypotheses with the Evolution agent, so subsequent papers avoid earlier mistakes — this is the path the ablation showed actually improves outputs. It also recalibrates world-model belief confidences from accumulated evidence (a heuristic scalar update persisted to the knowledge graph, with no measured downstream effect — kept for transparency). It does not claim on-device fine-tuning of a large neural network.
5. **Experiments.** It writes code, runs it in a sandbox, analyses results, and adjusts the next hypothesis.
6. **Honest about itself.** Every paper carries a Reflection block listing high / medium / low severity issues raised by an internal peer-review pass.

## Honest scope: what is real vs heuristic

A.M.Y deliberately separates **evidence-grade** capabilities (real scientific computation with verifiable provenance) from **heuristic / orchestration** layers. Read the comparison table below with this in mind.

**Genuinely real and verifiable:**
- **Scientific tool calls.** PySCF (`gto.Mole → scf.RHF → kernel`), ASE, AstroPy, RDKit, BioPython, SymPy, NumPy/SciPy, Z3 run the actual libraries and return real numbers. When a paper states a bond energy or HF total energy, it came from one of these.
- **Provenance.** Every tool run writes `data/experiments/<id>/provenance.json` + `output.txt`; the SHA-256 is the hash of the output, and the rubric scorer rejects manuscripts whose claimed hash does not match.
- **Ranking, Reflection, Meta-review, and Evolution agents.** Implemented and tested (Elo tournament, initial rating 1200; six-check reflection rubric — a deterministic *structural-conformity* checklist, not a quality grade or independent peer review; recurring-weakness synthesis; Co-Scientist Evolution agent with the paper's five refinement strategies).
- **Belief-weight recalibration.** `self_retrain` nudges world-model belief confidences toward their empirical reliability (a heuristic scalar moving average) and persists them. It is a real, persisted update to a scalar that exists — but the project's ablation measured **no downstream effect**, so it is honest bookkeeping, not a demonstrated quality lever. The Meta-review + Evolution loop is the part that moves outputs.
- **Curiosity module.** A working uncertainty + novelty + surprise heuristic inspired by ICM/RND — it is a heuristic, **not** the trained predictor networks of the original papers.

**Heuristic, optional, or environment-dependent (do not over-read):**
- **Paper Discussion.** Template-driven by default; LLM-written and provenance-grounded only with `AMY_USE_LLM_ENHANCER=1` and a reachable model.
- **Lean formal verification.** Runs the real Lean 4 kernel **only if a Lean toolchain is installed**; otherwise it returns `valid: false` with a reason (it never rubber-stamps an unchecked statement). Most installs do not ship Lean.
- **Active reproducibility engine.** Maps a paper's methods to tools and only executes steps whose required inputs can be resolved from the real method; steps with unresolved inputs are skipped and flagged, never run against fabricated placeholder data.
- **Many `atlas/app/services/` layers** contain explicit fallbacks/heuristics. Treat the service layer as orchestration scaffolding, not uniformly evidence-grade.

**Mock / demo-only (do NOT treat their numbers as real):**
- **AlphaFold 3 protein structure** (`atlas/app/domains/medicine/services/alphafold3_service.py`) is a **demo mock** that fabricates random pLDDT scores; it now **fails closed** by default (returns `success: false`) so its values cannot flow into downstream ranking — set `AMY_ALLOW_MOCK_ALPHAFOLD=1` only for clearly-labelled demo data. A *real* implementation (EBI AlphaFold DB + AlphaFold Server API + BioPython/RDKit) exists at `atlas/app/domains/medicine/personalized/alphafold3_service.py` and backs the FastAPI router.
- **ClinicalBERT NER** (`…/services/clinicalbert_service.py`) performs **keyword matching**, not transformer inference (it now honestly reports `analysis_method: keyword_fallback`). The real scispaCy/HF NER path is in `…/personalized/clinicalbert_service.py`.
- **Plasma "PINN" solver** and **additive-manufacturing microstructure** include simulated/hardcoded sub-results (the surrounding physics — plasma transport, the AM thermal/melt-pool FD sim — is real). These are not surfaced in the headline claims; treated as roadmap.

## Comparison with state-of-the-art (June 2026)

The "autonomously covered" and "papers per run" figures below measure A.M.Y's pipeline throughput (provenance-anchored computation + write-up), **not** externally peer-reviewed scientific validation. Unlike Sakana's workshop-accepted paper, A.M.Y's outputs have not been through external peer review; the comparison is of system capabilities, not of validated scientific impact.

| Aspect | Sakana AI Scientist v2 | Google Co-Scientist | Human-AI science case study | **A.M.Y** |
|---|---|---|---|---|
| Domains autonomously covered | 1 (ML) | ~2 (bio + chem) | 6 (assisted) | **23 (pipeline coverage)** |
| Papers in one run | 1 / 30 min | 1 / 60 min (assisted) | manual | **23 / 7 min (pipeline throughput)** |
| External peer-review validation | **Yes (1 workshop accept)** | Yes (Nature, wet-lab) | Yes | Not yet |
| Open source | Yes (no Nature artefact) | No | No | **Yes (Apache-2.0)** |
| Cryptographic provenance | LaTeX templates | Limited | Manual citations | **SHA-256, 100% verifiable** |
| Tournament Elo | No | Yes | No | **Yes (heuristic + LLM judge)** |
| Formal self-review | Yes (multi-LLM) | Yes (Reflection) | No | **Yes (Reflection + Meta-review)** |


## Responsible use

A.M.Y ships with a built-in misuse guard (atlas/app/security/misuse_guard.py) that fails closed and blocks operations in nine categories:

- Chemical weaponisation
- Biological weaponisation (gain-of-function, pathogen enhancement)
- Cyber abuse (exploits, malware, credential theft)
- Unauthorised human experimentation
- Guardrail tampering (disabling the safety policy itself)
- Fissile materials (synthesis, enrichment, weaponisation)
- Mass surveillance and individual targeting
- Critical infrastructure attack (power grid, SCADA, elections)
- Prompt injection and jailbreak attempts

The guard is enforced before any tool runs and again before any subprocess starts. If you ship a fork that disables it, you take ownership of that decision; please use a different name so users can tell the projects apart.

### Recommended sandbox profile (unattended / public deployment)

The shipped `config.yaml` uses the Docker tier in fail-closed mode. Generated experiment code runs in an ephemeral container with no network and a memory cap; if Docker is unavailable, A.M.Y refuses the experiment instead of silently weakening isolation:

```yaml
sandbox:
  use_docker: true          # ephemeral container, --network=none, memory cap
  require_isolation: true   # FAIL CLOSED: refuse to run if Docker is unavailable
  allow_network: false
  allow_subprocess: false
```

Prerequisite: `docker build -t amy-sandbox:latest sandbox/` with the daemon running. For trusted local development only, you may explicitly set both `use_docker: false` and `require_isolation: false`; that hardened-subprocess tier bounds accidents but is not a security boundary.

The capabilities A.M.Y orchestrates (PySCF, ASE, RDKit, AstroPy, BioPython, ClinicalBERT, etc.) are independently available in PyPI without guardrails. A.M.Y's contribution is orchestration, provenance, and refusal, not novel offensive capability.

By using A.M.Y you agree to the terms in USE_POLICY.md. To report a vulnerability in the guard or in the system, see SECURITY.md.

Every generated paper carries a machine-readable watermark identifying it as autonomously generated, with version and SHA-256 fingerprint, so the wider research ecosystem can detect and filter as it sees fit.

## Acknowledgements

A.M.Y stands on the shoulders of an enormous open-source community. None of this would exist without the people who chose to release their work freely. With deep gratitude:

### Scientific computing
- **NumPy, SciPy, pandas, matplotlib** - the foundation of computational science in Python
- **SymPy** - symbolic mathematics (BSD)
- **PySCF** - ab initio quantum chemistry, Hartree-Fock and DFT
- **ASE** (Atomic Simulation Environment) - geometry optimisation and thermochemistry
- **AstroPy** - cosmology, units, constants
- **PyMatGen** - crystal structures and materials properties
- **RDKit** - cheminformatics
- **BioPython** - biological sequence analysis
- **scikit-learn** - classical machine learning
- **Z3** - SMT solving / formal verification

### Machine learning and inference
- **PyTorch** (with MPS / Metal on Apple Silicon)
- **JAX, JAXlib** - Active Inference math
- **ChromaDB** - vector store for semantic memory
- **NetworkX** - the knowledge graph
- **Ollama Cloud** - the LLM backend
- **ClinicalBERT, DNABert2, AlphaFold 3** - domain models surfaced via Atlas (real integrations live in the `personalized/` service paths; see [Honest scope](#honest-scope-what-is-real-vs-heuristic))

### Engineering and runtime
- **structlog** - structured logging
- **httpx** - async HTTP client
- **pytest, pytest-asyncio** - test infrastructure
- **PyYAML, python-dotenv** - configuration
- **arxiv, feedparser, beautifulsoup4** - literature ingestion
- **rich** - the lovely terminal output

### Scientific and architectural inspiration
- **Karl Friston** - Active Inference and the Free Energy Principle
- **Bernard Baars and Stanislas Dehaene** - Global Workspace Theory
- **Laird, Newell, Rosenbloom** - the SOAR cognitive architecture
- **Pathak et al.** - Intrinsic Curiosity (ICM / RND)
- **Wang et al. (NVIDIA / Caltech)** - the Voyager paradigm
- **Tom Mitchell and the NELL team** - continual learning at scale
- **Sakana AI** - AI Scientist v2; the agentic tree search pattern
- **Google DeepMind** - the Co-Scientist multi-agent design and Elo tournament
- **arXiv:2511.16072 authors** - the science acceleration case studies that informed the flagship paper structure

### License
Apache License 2.0. See LICENSE. The project is dedicated to expanding human knowledge in a transparent, reproducible, and auditable way. Use it well.
