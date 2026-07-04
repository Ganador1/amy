# Chemistry SSH Novelty Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add and validate a deterministic SSH/polyene gap-map experiment that can produce a stronger chemistry paper with a defensible candidate novelty boundary.

**Architecture:** Extend the existing Atlas legacy registry with one pure NumPy tool, route the chemistry E2E plan through it, and pin behavior with focused tests. Keep existing Hückel, bond-alternated, and PySCF controls so the new paper has baseline, perturbation, and independent ab initio context.

**Tech Stack:** Python 3.13/3.14, NumPy, pytest, existing A.M.Y E2E harness.

---

### Task 1: Pin The New Tool Contract

**Files:**
- Modify: `tests/test_atlas_tools_end_to_end.py`
- Modify: `tests/test_production_harnesses.py`
- Modify: `tests/test_scientific_hardening.py`

- [ ] **Step 1: Add failing end-to-end tool test**

Add a test that calls `ssh_polyene_gap_map` through `ToolRegistry.execute_tool` with:

```python
"4,6,8,10,12,20,40;deltas=0,0.05,0.1,0.2;orientations=trivial,topological;beta=-2.5"
```

Assert the result contains:

```python
"SSH/polyene finite-chain gap map"
"identifiability_threshold_eV"
"orientation=topological"
"edge_state_warning"
"smallest_identifiable_n"
```

- [ ] **Step 2: Verify the test fails**

Run:

```bash
/Volumes/Ganador\ disk/A.M.Y/.venv/bin/python -m pytest tests/test_atlas_tools_end_to_end.py::test_ssh_polyene_gap_map_identifiability_contract -q
```

Expected: failure because the tool is not registered yet.

- [ ] **Step 3: Add harness test**

Update `test_e2e_chemistry_plan_targets_polyene_scaling` so it requires `ssh_polyene_gap_map` in `DOMAIN_PLANS["chemistry"]["calls"]`.

- [ ] **Step 4: Add hardening test**

Add a focused test that passes a synthetic `ssh_polyene_gap_map` result into the paper enhancer/hypothesis path and asserts generated hypotheses discuss finite-chain identifiability rather than generic bond-energy claims.

### Task 2: Implement `ssh_polyene_gap_map`

**Files:**
- Modify: `atlas/app/run_agent_with_tools_legacy.py`

- [ ] **Step 1: Register the tool**

Add a `ToolDescriptor` named `ssh_polyene_gap_map` in the chemistry section with output format `ssh_polyene_gap_map`.

- [ ] **Step 2: Implement parser**

Parse atom counts from the first segment. Parse `deltas=`, `orientations=`, `beta=`, and optional `threshold=` from semicolon options. Reject odd chain lengths, fewer than four lengths, negative deltas, and unknown orientations.

- [ ] **Step 3: Implement SSH diagonalization**

For each `n`, `delta`, and orientation:

```python
t0 = abs(beta)
t_strong = t0 * (1.0 + delta)
t_weak = t0 * (1.0 - delta)
```

Use open-boundary nearest-neighbor Hamiltonians with alternating couplings. The `trivial` orientation starts with strong coupling; `topological` starts with weak coupling.

- [ ] **Step 4: Report identifiability**

Compute `gap_delta - uniform_gap` for each length and report the smallest tested `n` where the difference exceeds `threshold`. Also report when the topological frontier gap is less than half the bulk Peierls estimate, as `edge_state_warning`.

- [ ] **Step 5: Run focused tests**

Run:

```bash
/Volumes/Ganador\ disk/A.M.Y/.venv/bin/python -m pytest tests/test_atlas_tools_end_to_end.py tests/test_production_harnesses.py::test_e2e_chemistry_plan_targets_polyene_scaling -q
```

Expected: pass.

### Task 3: Route Chemistry E2E Through The New Experiment

**Files:**
- Modify: `scripts/run/run_e2e_validation.py`
- Modify: `tests/test_production_harnesses.py`

- [ ] **Step 1: Update chemistry topic**

Set the chemistry topic to:

```text
SSH polyene finite-chain identifiability: Peierls gaps versus edge-state contamination
```

- [ ] **Step 2: Add primary tool call**

Insert `ssh_polyene_gap_map` as the first chemistry call with:

```text
4,6,8,10,12,16,20,30,40,60,80,100;deltas=0,0.025,0.05,0.1,0.2,0.4;orientations=trivial,topological;beta=-2.5;threshold=0.05
```

- [ ] **Step 3: Retain controls**

Keep `huckel_polyene_scaling`, `bond_alternated_polyene_scaling`, `pyscf_polyene_hf_gap`, and endpoint `molecular_orbital_energy` controls.

### Task 4: Generate And Evaluate A New Chemistry Paper

**Files:**
- Create: `experiments/e2e_validation/e2e_chemistry_*.json`
- Create: `experiments/e2e_validation/papers/E2E_Validation_SSH_polyene_*.md`
- Create: matching `.tex` and `.review.json`

- [ ] **Step 1: Run chemistry E2E**

Run:

```bash
AMY_USE_LLM_ENHANCER=1 AMY_USE_LLM_JUDGE=1 AMY_USE_EVOLUTION=1 AMY_ENHANCER_MODEL=glm-5.2 AMY_RANKING_MODEL=glm-5.2 /Volumes/Ganador\ disk/A.M.Y/.venv/bin/python scripts/run/run_e2e_validation.py --domain chemistry --config config.yaml
```

- [ ] **Step 2: Evaluate results**

Run:

```bash
/Volumes/Ganador\ disk/A.M.Y/.venv/bin/python scripts/run/branch_quality.py --latest-per-domain
```

Expected chemistry status: `target`; grounding repairs: `0`.

- [ ] **Step 3: Inspect paper novelty**

Read the new chemistry paper and verify:

- It does not claim a new material or DFT result.
- It distinguishes known controls from candidate novelty.
- It cites the SSH/polyene literature context.
- It reports the finite identifiability boundary produced by `ssh_polyene_gap_map`.

### Task 5: Final Verification

**Files:**
- All modified files and selected final E2E artifacts.

- [ ] **Step 1: Run static checks**

```bash
git diff --check
/Volumes/Ganador\ disk/A.M.Y/.venv/bin/python -m py_compile atlas/app/run_agent_with_tools_legacy.py scripts/run/run_e2e_validation.py
```

- [ ] **Step 2: Run focused regression suite**

```bash
/Volumes/Ganador\ disk/A.M.Y/.venv/bin/python -m pytest tests/test_atlas_tools_end_to_end.py tests/test_production_harnesses.py tests/test_scientific_hardening.py tests/test_branch_quality.py -q
```

- [ ] **Step 3: Summarize evidence**

Report the new chemistry rubric score, discussion score, repair count, paper path, and whether a candidate novelty claim is justified.
