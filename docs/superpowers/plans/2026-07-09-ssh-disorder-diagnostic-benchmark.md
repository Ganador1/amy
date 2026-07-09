# SSH Disorder Diagnostic Benchmark Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a deterministic Atlas benchmark for finite disordered SSH chains, run a preregistered primary/replication study, and publish a hashed reproducibility package and paper.

**Architecture:** Put all numerical and statistical logic in a pure module that has no Atlas process dependency. Register a thin Atlas adapter in the existing legacy tool registry, then use a dedicated A.M.Y study runner to call Atlas, record provenance, build tables/figures, generate the manuscript, and hash the release. Keep confirmatory and descriptive analyses distinct.

**Tech Stack:** Python 3.13/3.14, NumPy, SciPy-free exact binomial statistics, pytest, A.M.Y `AtlasTools`, `ProvenanceManager`, `PaperGenerator`, Matplotlib, LaTeX/PDF.

---

### Task 1: Pin Deterministic Seeds, Labels, and Diagnostic Rules

**Files:**
- Create: `tests/test_ssh_disorder_benchmark.py`
- Create: `atlas/app/ssh_disorder_benchmark.py`

- [ ] **Step 1: Write failing unit tests**

Add tests that import:

```python
from app.ssh_disorder_benchmark import (
    BenchmarkConfig,
    condition_seed,
    diagnostic_votes,
    random_ssh_label,
)
```

The tests must assert:

```python
cfg = BenchmarkConfig(
    lengths=(20,),
    deltas=(0.1,),
    strengths=(0.2,),
    disorder_types=("off_diagonal",),
    orientations=("trivial", "topological"),
    realizations=4,
    namespace="paired-test",
)
assert condition_seed(cfg, "off_diagonal", 20, 0.1, 0.2, 3, "trivial") == (
    condition_seed(cfg, "off_diagonal", 20, 0.1, 0.2, 3, "topological")
)
assert condition_seed(cfg, "off_diagonal", 20, 0.1, 0.2, 3, "trivial") != (
    condition_seed(cfg, "off_diagonal", 20, 0.1, 0.2, 4, "trivial")
)
assert random_ssh_label([0.8, 1.2, 0.8, 1.2, 0.8]) is True
assert random_ssh_label([1.2, 0.8, 1.2, 0.8, 1.2]) is False
assert diagnostic_votes(
    gap_ratio=0.1, edge_weight=0.7, normalized_ipr=1.0,
    gap_threshold=0.2, edge_threshold=0.5, ipr_threshold=2.5,
) == {"gap": True, "edge": True, "ipr": False, "gap_only": True, "joint": True}
```

Add validation tests rejecting odd lengths, deltas outside `(0, 1)`, negative
strengths, unknown disorder types, nonpositive realization counts, and empty
namespaces.

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
/Volumes/Ganador\ disk/A.M.Y/.venv/bin/python -m pytest tests/test_ssh_disorder_benchmark.py -q
```

Expected: collection fails because `app.ssh_disorder_benchmark` does not exist.

- [ ] **Step 3: Implement the minimal pure API**

Create `atlas/app/ssh_disorder_benchmark.py` with:

```python
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
```

Implement `__post_init__` validation. Implement `condition_seed` by hashing the
pipe-separated namespace, disorder type, length, decimal-normalized delta and
strength, and realization index; accept orientation but exclude it from the
hash. Convert the first eight digest bytes with
`int.from_bytes(..., "big", signed=False)`.

Implement `random_ssh_label` by splitting alternating bonds into intracell
indices `0,2,...` and intercell indices `1,3,...`, then comparing their mean
natural logarithms. Implement `diagnostic_votes` with the four frozen
thresholds in the design.

- [ ] **Step 4: Run tests and verify GREEN**

Run the Task 1 test command. Expected: all Task 1 tests pass.

- [ ] **Step 5: Commit**

```bash
git add atlas/app/ssh_disorder_benchmark.py tests/test_ssh_disorder_benchmark.py
git commit -m "feat: add deterministic SSH disorder benchmark core"
```

### Task 2: Exact Diagonalization and Statistical Summaries

**Files:**
- Modify: `tests/test_ssh_disorder_benchmark.py`
- Modify: `atlas/app/ssh_disorder_benchmark.py`

- [ ] **Step 1: Write failing numerical tests**

Add tests for `build_realization`, `frontier_metrics`, `wilson_interval`,
`exact_mcnemar_pvalue`, and `run_benchmark`. Pin these behaviors:

- zero-disorder topological and trivial chains reproduce the existing SSH
  Hamiltonian spectra to `1e-12`;
- off-diagonal realizations have exactly zero onsite terms and strictly
  positive hoppings;
- diagonal realizations retain clean hoppings and nonzero onsite terms;
- paired orientations receive identical random vectors;
- a perfectly localized vector has IPR 1 and edge weight 1;
- `exact_mcnemar_pvalue(0, 0) == 1.0`;
- `exact_mcnemar_pvalue(0, 10) == 2 / 2**10`;
- Wilson bounds stay in `[0, 1]`;
- a small benchmark emits deterministic realization records and condition
  summaries with accuracy, FPR, FNR, discordant counts, McNemar p-value, and
  diagonal-disorder accuracy fields set to `None`.

- [ ] **Step 2: Run the new tests and verify RED**

Run the Task 1 command. Expected: imports or assertions fail for the new API.

- [ ] **Step 3: Implement exact numerical functions**

Implement:

```python
def build_realization(config, disorder_type, n, delta, strength,
                      realization_index, orientation) -> tuple[np.ndarray, np.ndarray, int]
def frontier_metrics(onsite, hoppings, edge_sites) -> dict[str, float]
def wilson_interval(successes, total, z=1.959963984540054) -> tuple[float, float]
def exact_mcnemar_pvalue(gap_wrong_joint_right, gap_right_joint_wrong) -> float
def run_benchmark(config) -> dict[str, object]
def format_benchmark_report(result) -> str
```

Use `np.linalg.eigh` on the real symmetric tridiagonal Hamiltonian. Average
edge weight and IPR across the two frontier eigenvectors. Compute clean bulk
gap as `4*abs(beta)*delta`. For off-diagonal disorder, multiply clean
hoppings by `exp(W*z)`. For diagonal disorder, add `W*abs(beta)*z` onsite
terms. Generate the random vector once per condition seed and reuse it across
orientations.

At `W=0`, execute one unique realization and report `effective_realizations=1`
even when the configured count is larger. Store all per-realization records in
memory, but format only condition and pooled summaries in the Atlas text.

Implement the two-sided exact McNemar test as twice the lower binomial tail
with `p=0.5`, capped at 1.0. Calculate pooled H1 metrics only for
off-diagonal records. Include a canonical JSON `protocol` object and its
computed SHA-256 in the result; if `config.protocol_sha256` is nonempty, echo
and validate it separately as the preregistration hash.

- [ ] **Step 4: Run tests and verify GREEN**

Run the Task 1 command. Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add atlas/app/ssh_disorder_benchmark.py tests/test_ssh_disorder_benchmark.py
git commit -m "feat: benchmark SSH diagnostics under paired disorder"
```

### Task 3: Register the Atlas Tool

**Files:**
- Modify: `tests/test_atlas_tools_end_to_end.py`
- Modify: `atlas/app/run_agent_with_tools_legacy.py`

- [ ] **Step 1: Write a failing registry contract test**

Call:

```python
registry.execute_tool(
    "ssh_disorder_diagnostic_benchmark",
    (
        "20,40;deltas=0.1;strengths=0,0.2;"
        "disorders=off_diagonal,diagonal;"
        "orientations=trivial,topological;realizations=8;"
        "namespace=atlas-contract;protocol_sha256=" + "a" * 64
    ),
)
```

Assert the output includes:

```text
SSH disorder diagnostic benchmark
seed_derivation=sha256
paired_orientations=true
primary_estimand=error_gap_minus_error_joint
disorder_type=off_diagonal
disorder_type=diagonal
reference_label=not_defined
protocol_sha256=
preregistration_sha256=
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```bash
/Volumes/Ganador\ disk/A.M.Y/.venv/bin/python -m pytest tests/test_atlas_tools_end_to_end.py::test_ssh_disorder_diagnostic_benchmark_contract -q
```

Expected: failure because the tool is not registered.

- [ ] **Step 3: Add a thin parser and registry adapter**

In `run_agent_with_tools_legacy.py`, register a chemistry
`ToolDescriptor(name="ssh_disorder_diagnostic_benchmark", ...)`.

Add `_ssh_disorder_diagnostic_benchmark(self, query: str) -> str` that parses
the exact semicolon options shown in Step 1, constructs `BenchmarkConfig`,
calls `run_benchmark`, and returns `format_benchmark_report`. Return
`"Error: ..."` for validation failures, matching existing Atlas conventions.
Do not duplicate numerical logic in the legacy registry.

- [ ] **Step 4: Run focused and core tests**

Run:

```bash
/Volumes/Ganador\ disk/A.M.Y/.venv/bin/python -m pytest \
  tests/test_ssh_disorder_benchmark.py \
  tests/test_atlas_tools_end_to_end.py::test_ssh_disorder_diagnostic_benchmark_contract -q
```

Expected: all selected tests pass.

- [ ] **Step 5: Commit**

```bash
git add atlas/app/run_agent_with_tools_legacy.py tests/test_atlas_tools_end_to_end.py
git commit -m "feat: expose SSH disorder benchmark through Atlas"
```

### Task 4: Route A.M.Y and Enforce Scientific Wording

**Files:**
- Modify: `tests/test_production_harnesses.py`
- Modify: `tests/test_scientific_hardening.py`
- Modify: `scripts/run/run_e2e_validation.py`
- Modify: `communication/paper_enhancer.py`

- [ ] **Step 1: Write failing pipeline and wording tests**

Require the chemistry plan to include two
`ssh_disorder_diagnostic_benchmark` calls whose namespaces are
`amy-ssh-disorder-v1-primary` and `amy-ssh-disorder-v1-replication`.

Add an enhancer test with a synthetic benchmark result. Require its generated
hypothesis and method to mention `paired`, `McNemar`, `gap-only`, `joint`, and
`candidate methodological novelty`. Require the limitation text to state that
diagonal disorder has no chiral topological reference label and that the
tight-binding model is not an experimental material result.

- [ ] **Step 2: Run the tests and verify RED**

Run:

```bash
/Volumes/Ganador\ disk/A.M.Y/.venv/bin/python -m pytest \
  tests/test_production_harnesses.py::test_e2e_chemistry_plan_includes_preregistered_disorder_replication \
  tests/test_scientific_hardening.py::test_ssh_disorder_benchmark_hypothesis_is_methodological -q
```

Expected: both tests fail before routing and wording support exist.

- [ ] **Step 3: Add the two Atlas calls and domain-aware text**

Prepend the primary and replication calls to the chemistry `DOMAIN_PLANS`
entry with the exact grid from the design and `realizations=128`. Keep the
existing clean SSH and PySCF controls.

Add a `ssh_disorder_diagnostic_benchmark` entry to `TOOL_CONTEXTS`. Extend
`generate_hypothesis`, discussion generation, references, non-claims, and
methodology text through the existing tool-specific branches. Treat the pooled
paired comparison as a benchmark result and diagonal disorder as a negative
control. Never label a diagonal-disorder positive as a topological phase.

- [ ] **Step 4: Run the selected tests and verify GREEN**

Run the Step 2 command. Expected: both pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/run/run_e2e_validation.py communication/paper_enhancer.py \
  tests/test_production_harnesses.py tests/test_scientific_hardening.py
git commit -m "feat: route chemistry papers through disorder benchmark"
```

### Task 5: Preregister and Build the Study Runner

**Files:**
- Create: `experiments/ssh_disorder_study/preregistration.json`
- Create: `tests/test_ssh_disorder_study.py`
- Create: `scripts/run/run_ssh_disorder_study.py`

- [ ] **Step 1: Write the preregistration before execution**

Create canonical JSON containing the full grid, H1-H3, alpha, frozen
thresholds, primary and replication namespaces, exact seed formula, no
exclusions, all planned outputs, and the literature-positioning caveat. Do not
include observed results. Compute its SHA-256 only after the file is final.

- [ ] **Step 2: Write failing runner tests**

Test pure helpers that:

- hash a file with SHA-256;
- parse Atlas `summary` and `pooled` rows without silently dropping fields;
- reject an Atlas output whose preregistration hash differs;
- write condition CSV/JSON with primary/replication labels;
- build a manuscript result summary that reports H1/H2 whether supported or
  not;
- create a manifest with relative paths and verify all entries.

- [ ] **Step 3: Run runner tests and verify RED**

Run:

```bash
/Volumes/Ganador\ disk/A.M.Y/.venv/bin/python -m pytest tests/test_ssh_disorder_study.py -q
```

Expected: collection fails because the runner module does not exist.

- [ ] **Step 4: Implement the study runner**

The runner must:

1. hash the preregistration;
2. call `AtlasTools.run_scientific_tool` for primary and replication with
   `domain="chemistry"` and the preregistration hash;
3. reject unusable output through `assess_tool_output`;
4. use `ProvenanceManager` to create experiment IDs and SHA-256 records;
5. save raw Atlas text, parsed condition CSV/JSON, and pooled JSON;
6. generate two figures: paired error rates with Wilson intervals, and
   diagonal-disorder positive rates clearly labeled as a negative control;
7. use `PaperGenerator` with deterministic sections grounded in parsed results;
8. save the literature search JSON returned by `AtlasTools.search_literature`;
9. create and verify `MANIFEST.sha256`.

Support `--smoke` to use lengths `20,40`, delta `0.1`, strengths `0,0.2`, and
eight realizations without modifying the preregistered production defaults.

- [ ] **Step 5: Run tests and smoke execution**

Run:

```bash
/Volumes/Ganador\ disk/A.M.Y/.venv/bin/python -m pytest tests/test_ssh_disorder_study.py -q
AMY_ATLAS_PYTHON=/Volumes/Ganador\ disk/A.M.Y/atlas/.venv_new/bin/python3 \
  /Volumes/Ganador\ disk/A.M.Y/.venv/bin/python \
  scripts/run/run_ssh_disorder_study.py --smoke
```

Expected: tests pass; smoke run emits two valid Atlas experiment IDs and a
manifest that verifies.

- [ ] **Step 6: Commit**

```bash
git add experiments/ssh_disorder_study/preregistration.json \
  scripts/run/run_ssh_disorder_study.py tests/test_ssh_disorder_study.py
git commit -m "feat: preregister and run hashed SSH disorder study"
```

### Task 6: Execute Primary and Replication Experiments

**Files:**
- Create: `experiments/ssh_disorder_study/release/*`
- Create: `data/experiments/<primary-id>/provenance.json`
- Create: `data/experiments/<replication-id>/provenance.json`

- [ ] **Step 1: Record frozen preregistration hash**

Run:

```bash
shasum -a 256 experiments/ssh_disorder_study/preregistration.json
```

Record the digest in the execution log without editing the preregistration.

- [ ] **Step 2: Run the production study through Atlas**

Run:

```bash
AMY_ATLAS_PYTHON=/Volumes/Ganador\ disk/A.M.Y/atlas/.venv_new/bin/python3 \
  /Volumes/Ganador\ disk/A.M.Y/.venv/bin/python \
  scripts/run/run_ssh_disorder_study.py
```

Expected: primary and replication Atlas calls succeed, output assessment is
usable, provenance hashes verify, and the release directory is populated.

- [ ] **Step 3: Re-run determinism check**

Run the same benchmark calls into a temporary directory and compare SHA-256 of
the raw primary and replication Atlas text. Expected: byte-identical output for
each namespace.

- [ ] **Step 4: Inspect the scientific decision**

Read pooled JSON and confirm the manuscript reports:

- actual paired error difference and 95% interval;
- exact McNemar discordant counts and p-value;
- whether H1 passed;
- whether the sign and conclusion replicated;
- diagonal-disorder results only as descriptive negative controls.

Do not alter thresholds or hypotheses based on observed values.

### Task 7: Paper and Reproducibility Audit

**Files:**
- Modify only if verification exposes a tested defect in code or layout.

- [ ] **Step 1: Verify hashes**

From the release directory, run:

```bash
shasum -a 256 -c MANIFEST.sha256
```

Expected: every artifact reports `OK`.

- [ ] **Step 2: Run focused and regression tests**

Run:

```bash
/Volumes/Ganador\ disk/A.M.Y/.venv/bin/python -m pytest \
  tests/test_ssh_disorder_benchmark.py \
  tests/test_ssh_disorder_study.py \
  tests/test_atlas_tools_end_to_end.py \
  tests/test_production_harnesses.py \
  tests/test_scientific_hardening.py \
  tests/test_publication_artifacts.py -q
```

Separate the two known preexisting `test_scientific_hardening.py` failures from
any new failure. Fix only defects caused by this branch unless a preexisting
failure blocks the paper's scientific integrity.

- [ ] **Step 3: Verify syntax and diff hygiene**

Run:

```bash
/Volumes/Ganador\ disk/A.M.Y/.venv/bin/python -m py_compile \
  atlas/app/ssh_disorder_benchmark.py \
  scripts/run/run_ssh_disorder_study.py \
  atlas/app/run_agent_with_tools_legacy.py
git diff --check HEAD^
```

Expected: exit code 0.

- [ ] **Step 4: Render and inspect the PDF**

Render all PDF pages to PNG, inspect every page, and correct clipping, broken
references, malformed equations, missing figure labels, or unreadably small
tables. Rebuild and re-check the manifest after any change.

- [ ] **Step 5: Audit scientific reporting**

Check the final manuscript against the acceptance criteria in the design:
methods, controls, uncertainty, effect size, confirmatory/descriptive
separation, falsification outcome, limitations, data/code availability,
conflicts, funding, contributions, AI disclosure, citations, provenance IDs,
preregistration hash, and release manifest.

- [ ] **Step 6: Final verification commit**

After all fresh verification commands pass:

```bash
git add atlas/app/ssh_disorder_benchmark.py atlas/app/run_agent_with_tools_legacy.py \
  communication/paper_enhancer.py scripts/run/run_e2e_validation.py \
  scripts/run/run_ssh_disorder_study.py tests \
  experiments/ssh_disorder_study
git commit -m "research: publish reproducible SSH disorder benchmark"
```
