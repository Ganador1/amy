# SSH Disorder Diagnostic Benchmark Design

## Goal

Extend A.M.Y.'s Atlas chemistry branch from clean finite-chain SSH sweeps to a
preregistered, reproducible benchmark of edge-state diagnostics under quenched
disorder. The study will quantify when a frontier-gap-only rule disagrees with
a joint spectral-and-localization rule, using exact diagonalization, paired
disorder realizations, deterministic hash-derived seeds, confidence intervals,
an independent replication namespace, and SHA-256 manifests.

The paper's defensible novelty claim is methodological: an auditable,
condition-level error map for two fixed diagnostics on paired finite disordered
SSH chains. It will not claim a new topological phase, a new material, a wet-lab
result, or proof that no prior related analysis exists.

## Alternatives Considered

1. **Deeper clean-chain finite-size scaling.** This is inexpensive and has
   analytic controls, but the existing A.M.Y branch already covers the clean
   gap and edge-localization problem. Additional sweeps would be incremental.
2. **Paired disorder diagnostic benchmark (selected).** This directly improves
   the current branch, adds a statistical estimand and a symmetry-breaking
   negative control, and remains fully reproducible on local hardware.
3. **Ab-initio oligomer benchmark.** This is chemically more realistic, but a
   sufficiently powered geometry and basis-set study would be expensive and
   would still not establish experimental validity without external data.

## Scientific Question and Hypotheses

The primary question is whether a fixed joint diagnostic using frontier
splitting, frontier-pair edge weight, and inverse participation ratio (IPR)
reduces classification error relative to a frontier-gap-only rule in finite
SSH chains with chiral-symmetry-preserving off-diagonal disorder.

- **H1 (primary):** On pooled paired off-diagonal-disorder realizations, the
  joint rule has lower error than the gap-only rule. The confirmatory test is a
  two-sided exact McNemar test at alpha 0.05, accompanied by the paired error
  difference and a bootstrap 95% confidence interval.
- **H2 (replication):** The sign of the pooled error difference and the H1
  conclusion reproduce under a second seed namespace fixed before execution.
- **H3 (negative control):** Under diagonal disorder, which breaks chiral
  symmetry, localization-based positives cannot be interpreted as topology.
  Positive rates are reported descriptively, without accuracy or topological
  ground-truth claims.

Failure to reject H1, a reversed error difference, or failure to reproduce the
direction in H2 falsifies the proposed superiority claim. The paper must report
that outcome without changing thresholds post hoc.

## Model and Paired Design

For an even open chain of `N` sites, the clean hopping magnitudes are
`t0 * (1 +/- delta)`. A topological termination starts with the weak
intracell bond; a trivial termination starts with the strong intracell bond.

The preregistered grid is:

- `N = {20, 40, 80}`
- `delta = {0.05, 0.10, 0.20}`
- dimensionless disorder strength `W = {0.00, 0.05, 0.10, 0.20, 0.40}`
- orientations `{trivial, topological}`
- disorder types `{off_diagonal, diagonal}`
- 128 realizations per nonzero condition and one deterministic realization at
  `W = 0`
- primary namespace `amy-ssh-disorder-v1-primary`
- replication namespace `amy-ssh-disorder-v1-replication`

For off-diagonal disorder, each positive hopping is multiplied by
`exp(W*z_i)`, with `z_i ~ Uniform(-1, 1)`. This preserves chiral symmetry and
avoids sign or zero-hopping artifacts. For diagonal disorder, onsite energies
are `W*t0*z_i`, with all clean hoppings unchanged.

The random vectors are paired across boundary orientations. A realization seed
is the first unsigned 64 bits of:

```text
SHA256(namespace | disorder_type | N | delta | W | realization_index)
```

Orientation is deliberately absent from the seed key. The protocol hash and
seed derivation are emitted by Atlas and included in provenance.

## Reference Labels and Diagnostics

For off-diagonal disorder only, the reference label is the real-space random
SSH criterion

```text
mean(log(intercell hopping)) > mean(log(intracell hopping)).
```

This label is not applied to diagonal disorder because onsite terms break the
protecting chiral symmetry.

For each realization, exact symmetric eigendecomposition provides the two
frontier eigenpairs. The fixed diagnostics are:

- gap vote: `frontier_splitting / clean_bulk_gap <= 0.20`
- edge vote: mean frontier-pair probability in the first and last two sites
  `>= 0.50`
- localization vote: `N * mean_frontier_pair_IPR >= 2.50`
- gap-only prediction: gap vote
- joint prediction: at least two of the three votes

Thresholds are fixed in the preregistration and are not tuned on experiment
outcomes.

## Statistical Analysis

For every off-diagonal condition and pooled across the complete grid, report:

- accuracy, false-positive rate, and false-negative rate for each rule;
- Wilson 95% confidence intervals for binomial proportions;
- paired error difference `error_gap - error_joint`;
- exact McNemar discordant counts and p-value;
- the count of realizations whose random-SSH reference label differs from the
  clean termination label.

The pooled H1 test is the only confirmatory p-value. Condition-level tests and
diagonal-disorder positive rates are descriptive. The replication namespace is
an exact repeat of the frozen protocol with new hash-derived random streams.

## Atlas Architecture

- Add an Atlas tool named `ssh_disorder_diagnostic_benchmark` to
  `atlas/app/run_agent_with_tools_legacy.py`.
- Keep numerical helpers pure and deterministic so tests can verify seed
  pairing, labels, diagnostics, confidence intervals, and exact McNemar output.
- Route the chemistry E2E plan through two calls to the new tool (primary and
  replication), while retaining the clean gap map, localization map, and
  small-polyene controls.
- Extend A.M.Y's paper enhancer and publication-artifact plotting so the new
  output is described as a benchmark, not as a material discovery.

## Provenance and Publication Artifacts

Before the first experimental run, create a preregistration JSON containing the
full grid, hypotheses, thresholds, exclusion policy (`none`), seed namespaces,
software versions, and planned analyses. Its SHA-256 is passed into both Atlas
calls.

Each successful Atlas call receives an experiment ID and
`data/experiments/<id>/provenance.json` with the full output hash. The curated
study directory will contain:

- preregistration JSON and its SHA-256;
- primary and replication Atlas outputs;
- condition-level CSV/JSON tables;
- figures;
- literature search/audit records;
- Markdown, LaTeX, and PDF manuscripts;
- `MANIFEST.sha256` covering every released artifact.

The manuscript must distinguish computational observations, established
literature, inferences, and limitations. It must include model equations,
software/hardware context, sample counts, uncertainty, effect sizes, exact
p-values where used, all exclusions, data/code availability, conflicts,
funding, author-contribution status, and an explicit AI-generation disclosure.

## Literature Positioning

The introduction and novelty audit will treat the following as established
controls:

- the SSH/polyacetylene model and boundary states;
- finite-size edge-state hybridization;
- IPR and edge weight as localization diagnostics;
- robustness of chiral SSH edge modes to off-diagonal disorder;
- loss of the ordinary winding-number interpretation under diagonal disorder.

Nearby work includes Pérez-González et al. on diagonal/off-diagonal disorder
in extended SSH chains (arXiv:1802.03973), Yao et al. on disordered topological
coherence (DOI:10.1103/PhysRevA.104.012216), and Kvande et al. on finite SSH
chains with onsite disorder (arXiv:2307.05824). Absence of an exact-match result
from automated searches is not proof of novelty; the final claim remains
“candidate methodological novelty pending external peer review.”

## Acceptance Criteria

1. Tool contract, seed pairing, statistics, invalid inputs, and paper wording
   are covered by tests written before implementation.
2. Primary and replication runs complete through `AtlasTools`, with no mock or
   placeholder evidence and valid SHA-256 provenance.
3. The frozen preregistration hash matches the hash cited in every result.
4. The paper reports the observed result even if H1 or H2 fails.
5. A clean-environment rerun reproduces byte-identical Atlas text outputs for
   each namespace.
6. `MANIFEST.sha256` verifies every curated artifact.
7. The PDF is rendered and visually inspected for clipping, broken tables,
   missing figures, and unreadable text.
