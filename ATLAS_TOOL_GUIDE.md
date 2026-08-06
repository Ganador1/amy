# A.M.Y → Atlas Tool Integration Guide

## Overview

A.M.Y (Autonomous Mind Yield) integrates with AXIOM Atlas through two interfaces:

1. **`AtlasTools`** (`core/atlas_tools.py`) — Direct tool execution, literature search, hypothesis verification
2. **`AtlasBridge`** (`core/atlas_bridge.py`) — Full research cycle with peer review and paper generation

## Architecture

```
A.M.Y Reasoning Engine
        │
        ├── AtlasTools.run_scientific_tool()  ← Direct tool calls
        ├── AtlasTools.search_literature()      ← Literature search
        ├── AtlasTools.verify_hypothesis()      ← Hypothesis verification
        └── AtlasBridge.run_research()          ← Full research cycle
                │
                ▼
        DynamicToolRegistry (100+ tools discovered at runtime)
                │
        ┌───────┼───────┬───────────┬──────────┐
        │       │       │           │          │
   Mathematics Chemistry Physics  Biology  Statistics
   (20 tools) (15)      (10)      (7)      (5)
        │       │       │           │          │
   ... 20+ more domains
```

## Tool Input Formats

Many legacy Atlas tools use **colon-separated** (`:`) inputs, but formats vary
by tool. Treat the live `input_format` returned by
`await tools.describe_tools()` as authoritative; the examples below cover the
most common static tools.

### Mathematics (20 tools)

| Tool | Input Format | Example | Output |
|------|-------------|---------|--------|
| `sympy_solve_equation` | `equation` | `x**2 - 4 = 0` | Solutions: [-2, 2] |
| `sympy_simplify` | `expression` | `sin(x)**2 + cos(x)**2` | Simplified: 1 |
| `sympy_derivative` | `expression, variable` | `x**3, x` | Derivative: 3*x**2 |
| `sympy_integrate` | `expression, variable` | `x**2, x` | Integral: x**3/3 |
| `sympy_prime_analysis` | `operation:number` | `is_prime:97` | 97 is prime: True |
| `number_theory_advanced` | `operation:number` | `goldbach:100` | Goldbach verification |
| `prime_gap_analysis` | `number` | `50000` | Gap distribution |
| `calculus_engine` | `operation:expr:var[:point]` | `limit:sin(x)/x:x->0` | Result: 1 |
| `symbolic_calculus` | `operation:expr:var[:point[:order]]` | `taylor:sin(x):x:0:5` | Taylor series |
| `graph_theory` | `operation:graph_spec` | `chromatic:petersen` | Chromatic number |
| `sequence_analyzer` | `operation:data` | `analyze:1,1,2,3,5,8,13` | Sequence analysis |
| `conjecture_engine` | `operation:domain` | `generate:number_theory` | Conjecture generation |
| `topology_invariants` | `invariant:space` | `euler_char:torus` | Euler characteristic |
| `automated_prover` | `method:statement` | `induction:sum(1..n)=n*(n+1)/2` | Formal proof |
| `z3_prover` | `verify:statement` | `verify, x + 0 == x` | Z3 verification |
| `z3_verify_theorem` | `verify:statement` | `verify, (x and y) implies (x or y)` | Theorem verification |
| `mathematical_discovery` | `method:domain[:params]` | `pattern_analysis:sequences` | Pattern discovery |
| `julia_computation` | `library:code` | `eigenvalues:[[1,2],[3,4]]` | Julia computation |
| `service_arithmeticservice` | `operation, args` | `gcd, 48, 36` | Arithmetic result |
| `evidence_corroborate_mathematics` | `hypothesis text` | `twin primes are infinite` | Evidence score |

### Chemistry (15 tools)

| Tool | Input Format | Example |
|------|-------------|---------|
| `molecular_weight_calc` | `formula` | `C6H12O6` |
| `computational_chemistry` | `operation:formula` | `analyze_molecule:C6H6` |
| `bond_energy_analyzer` | `bond_type` | `C-C` |
| `molecular_orbital_energy` | `n_atoms:bond_length` | `6:1.4` |
| `gnome_materials` | `operation:formula` | `stability:Li2O` |
| `evidence_corroborate_chemistry` | `hypothesis text` | `catalysis reduces activation energy` |

### Physics (10 tools)

| Tool | Input Format | Example |
|------|-------------|---------|
| `quantum_energy_levels` | `system:params` | `hydrogen:3` |
| `quantum_circuit` | `circuit_type:params` | `bell:2` |

### Biology (7 tools)

| Tool | Input Format | Example |
|------|-------------|---------|
| `dna_analyzer` | `DNA sequence` | `ATCGATCGATCGATCGATCG` |
| `protein_properties` | `amino acid sequence` | `MVLSPADKTNVKAAWGKVGA` |
| `dnabert2_analysis` | `operation:sequence` | `motifs:ATCGATCGATCG` |

### Statistics (5 tools)

| Tool | Input Format | Example |
|------|-------------|---------|
| `hypothesis_tester` | `test: data1: data2` | `ttest: [1,2,3,4,5]: [3,4,5,6,7]` |
| `correlation_analysis` | `data1: data2` | `[1,2,3,4,5]: [2,4,6,8,10]` |
| `numpy_correlation` | `arr1;arr2` | `[1,2,3,4,5];[2,4,6,8,10]` |
| `numpy_distribution` | `dist_type:n,mean,std` | `normal:1000,0,1` |
| `numpy_statistics` | `operation:data` | `summary:[1,2,3,4,5,6,7,8,9,10]` |

### Research (3 tools)

| Tool | Input Format | Example |
|------|-------------|---------|
| `literature_search` | `query text` | `prime gaps distribution` |
| `validate_hypothesis` | `domain:hypothesis` | `mathematics:prime gaps are not normally distributed` |

## Usage from A.M.Y

### Direct Tool Execution

```python
from core.atlas_tools import AtlasTools

tools = AtlasTools()

# Optional: move the one-time worker startup cost outside a latency-sensitive
# operation. The same owned worker is then reused until close().
startup = await tools.warm_up()
print(startup["last_startup_seconds"])

# List available tools
all_tools = await tools.list_tools()           # live, discovery-driven count
math_tools = await tools.list_tools("mathematics")  # Filter by domain

# Execute a tool
result = await tools.run_scientific_tool(
    "sympy_prime_analysis",  # tool name
    "is_prime:97",           # tool input
    "mathematics"            # domain
)
# Returns: "97 is prime: True"

# Reap the persistent worker before this event loop closes
await tools.close()
```

### Literature Search

```python
result = await tools.search_literature(
    "prime gaps distribution",
    domain="mathematics",
    max_results=8
)
# The domain/topic relevance gate runs before citation-count ranking. Each
# retained paper includes relevance_score/relevance_matches; the envelope also
# reports papers_filtered_irrelevant for audit.
# Returns: {"papers": [...], "support_score": float,
#           "relevance_filter_applied": True,
#           "papers_filtered_irrelevant": int, ...}
```

### Hypothesis Verification

```python
result = await tools.verify_hypothesis(
    "prime gaps follow an exponential distribution",
    domain="mathematics"
)
# Returns: {"support_score": 0.28, "papers": [...], ...}
```

### Full Research Cycle with Peer Review

```python
from core.atlas_bridge import AtlasBridge

bridge = AtlasBridge()
result = await bridge.run_research(
    domain="mathematics",
    topic="Distribution of prime gaps",
    hypothesis="Prime gaps follow an exponential distribution",
    max_iterations=3,
    target_score=7
)
# Returns: {"success": True, "paper": "...", "score": 8, "accepted": True, ...}
```

### Paper Writing with Tool Results

When A.M.Y writes a paper after executing Atlas tools, the results are automatically integrated:

```python
# After running tools...
await heartbeat._act_run_scientific_tool({
    "tool_name": "prime_gap_analysis",
    "tool_input": "1000",
    "domain": "mathematics"
})

# ...writing a paper includes tool results:
await heartbeat._act_write_paper({
    "paper_topic": "Prime Gap Analysis",
})
# Paper includes:
# - "Computational Verification" section with tool outputs
# - "Data Availability" section with experiment IDs
# - Tool results cited as evidence in the paper
```

### Peer Review with Tool Evidence

When submitting for peer review, tool results are included as facts:

```python
await heartbeat._act_peer_review_paper({
    "hypothesis": "Prime gaps are not normally distributed",
    "domain": "mathematics",
})
# Peer review receives:
# - Tool execution results as facts (confidence: 95%)
# - Computational verification as supporting evidence
# - Quality gate evaluation with marked content
```

## Historical Test Results

The fixed counts below are a historical snapshot of the earlier 94-tool
registry. The current registry is dynamic and exposes 100+ tools; use
`AtlasTools.describe_tools()` or `scripts/diagnostics/verify_atlas_tools.py`
for the authoritative count and current result on your installation.

### Exhaustive Atlas Tool Validation (legacy 94/94 snapshot)

All 94 tools in the DynamicToolRegistry pass with correct input formats.

### A.M.Y → Atlas Integration (6/6 = 100%)

| Test | Result |
|------|--------|
| AtlasTools availability | ✅ PASS |
| List tools (legacy 94-tool snapshot, 23 domains) | ✅ PASS |
| Direct tool execution (26 tools) | ✅ PASS |
| Literature search | ✅ PASS |
| Hypothesis verification | ✅ PASS |
| AtlasBridge availability | ✅ PASS |

### Heartbeat → Atlas Tool Invocation (6/6 = 100%)

| Test | Result |
|------|--------|
| sympy_prime_analysis | ✅ PASS |
| molecular_weight_calc | ✅ PASS |
| numpy_statistics | ✅ PASS |
| Episodic memory storage | ✅ PASS |
| World model update | ✅ PASS |
| AtlasTools availability | ✅ PASS |

### Full Cognitive Cycle with Atlas Tools (9/9 = 100%)

| Test | Result |
|------|--------|
| Cognitive architecture init | ✅ PASS |
| prime_gap_analysis execution | ✅ PASS |
| number_theory_advanced (Goldbach) | ✅ PASS |
| sympy_prime_analysis | ✅ PASS |
| validate_hypothesis | ✅ PASS |
| numpy_statistics | ✅ PASS |
| Episodic memory (5 events) | ✅ PASS |
| World model (6 beliefs) | ✅ PASS |
| Atlas integration | ✅ PASS |

### Sandbox + Atlas Integration (3/3 = 100%)

| Test | Result |
|------|--------|
| Sandbox → sympy_prime_analysis | ✅ PASS |
| Sandbox → numpy_statistics | ✅ PASS |
| Sandbox → validate_hypothesis | ✅ PASS |

### Paper Writing + Atlas Tools Integration (4/4 = 100%)

| Test | Result |
|------|--------|
| Tool results stored in history | ✅ PASS |
| Tool sections in paper | ✅ PASS |
| Experiment IDs generated | ✅ PASS |
| Episodic memory records tools_used | ✅ PASS |

### End-to-End Pipeline: Tools → Paper → Peer Review (4/4 = 100%)

| Test | Result |
|------|--------|
| Tool executions | ✅ PASS |
| Tool results stored | ✅ PASS |
| Paper written with tools | ✅ PASS |
| Tool facts for peer review | ✅ PASS |

### Multi-Domain Scientific Missions (10/10 = 100%)

| Domain | Tools OK | Coherence | Method | Utility | Overall |
|--------|----------|-----------|--------|---------|---------|
| Mathematics | 3/3 | 8/10 | 9/10 | 9/10 | 8.7/10 |
| Chemistry | 3/3 | 8/10 | 9/10 | 9/10 | 8.7/10 |
| Physics | 2/2 | 8/10 | 9/10 | 7/10 | 8.0/10 |
| Biology | 2/2 | 8/10 | 9/10 | 7/10 | 8.0/10 |
| **Average** | **10/10** | **8.0/10** | **9.0/10** | **8.0/10** | **8.3/10** |

### Paper Quality Across Domains (3/3 = 100%)

| Domain | Structure | Coherence | Evidence | Method | Overall |
|--------|-----------|-----------|----------|--------|---------|
| Mathematics | 8/10 | 8/10 | 7/10 | 10/10 | 8.2/10 |
| Chemistry | 8/10 | 8/10 | 7/10 | 10/10 | 8.2/10 |
| Physics | 8/10 | 8/10 | 7/10 | 10/10 | 8.2/10 |
| **Average** | **8.0/10** | **8.0/10** | **7.0/10** | **10.0/10** | **8.2/10** |

### Scientific Method Verification (3/3 = 100%)

| Domain | Structure | Evidence | Coherence | Overall |
|--------|-----------|----------|-----------|---------|
| Mathematics | 10/10 | 10/10 | 10/10 | **10.0/10** |
| Chemistry | 10/10 | 10/10 | 10/10 | **10.0/10** |
| Physics | 10/10 | 10/10 | 10/10 | **10.0/10** |
| **Average** | **10.0/10** | **10.0/10** | **10.0/10** | **10.0/10** |

**Verified:**
- ✅ All 6 required sections (Abstract, Introduction, Methods, Results, Discussion, Conclusion)
- ✅ Computational results with numerical data
- ✅ Conclusions based on results
- ✅ References and Data Availability sections
- ✅ All tools cited in the paper

### Robustness & Recovery (5/5 = 100%)

| Test | Result |
|------|--------|
| Atlas after system restart | ✅ PASS |
| Memory leak check (< 50MB) | ✅ PASS |
| Papers validity (5/5) | ✅ PASS |
| No zombie processes | ✅ PASS |
| Reports integrity | ✅ PASS |

### Peer Review Safety

| Test | Result |
|------|--------|
| Timeout protection (30s) | ✅ PASS |
| No system freeze | ✅ PASS |
| Clean process termination | ✅ PASS |

**Current behavior:** `AtlasBridge` has its own configurable deadline
(`atlas.peer_review_timeout_seconds`, 90 seconds by default), terminates the
whole subprocess group on timeout or cancellation, and reaps the direct child.
Tests may still use a shorter configured deadline.

### Edge Cases & Error Handling (7/8 = 87.5%)

| Test | Result |
|------|--------|
| Invalid input | ✅ PASS |
| Non-existent tool | ✅ PASS |
| Empty input | ✅ PASS |
| Wrong domain | ✅ PASS |
| Large input (1000 chars) | ✅ PASS |
| Special characters | ✅ PASS |
| Unicode input | ✅ PASS |
| Rapid successive calls | ⚠️ TIMEOUT (10 concurrent subprocesses) |

**Note:** Rapid calls timeout because each tool spawns a subprocess. Use `asyncio.Semaphore(3)` to limit concurrency.

### Deep Mathematics Mission (5/5 = 100%)

| Tool | Result |
|------|--------|
| prime_gap_analysis | ✅ 168 primes, mean gap 5.96 |
| sympy_prime_analysis | ✅ 97 is prime |
| number_theory_advanced | ✅ Goldbach verified to 100 |
| sympy_solve_equation | ✅ Solutions: [-2, 2] |
| sympy_derivative | ✅ Derivative: 3*x**2 |
| **Paper** | ✅ 360 words, 5 sections, all tools cited |

## Historical Test Suite Summary

| Test Suite | Tests | Pass Rate | Avg Quality |
|------------|-------|-----------|-------------|
| Atlas Exhaustive (legacy snapshot) | 94/94 | 100% | N/A |
| A.M.Y → Atlas Integration | 6/6 | 100% | N/A |
| Heartbeat → Atlas Tools | 6/6 | 100% | N/A |
| Cognitive Cycle | 9/9 | 100% | N/A |
| Sandbox + Atlas | 3/3 | 100% | N/A |
| Paper + Tools Integration | 4/4 | 100% | N/A |
| End-to-End Pipeline | 4/4 | 100% | N/A |
| Multi-Domain Missions | 10/10 | 100% | 8.3/10 |
| Paper Quality | 3/3 | 100% | 8.2/10 |
| Scientific Method | 3/3 | 100% | 10.0/10 |
| Robustness & Recovery | 5/5 | 100% | N/A |
| Peer Review Safety | 3/3 | 100% | N/A |
| Edge Cases | 7/8 | 87.5% | N/A |
| Deep Mathematics Mission | 5/5 | 100% | 9.5/10 |
| **TOTAL** | **80/81** | **98.8%** | **9.2/10** |

## Key Design Patterns

1. **Descriptor-driven inputs**: read each tool's live `input_format`; many legacy tools use `operation:data`
2. **Semicolon for arrays**: `numpy_correlation` uses `;` to separate two arrays
3. **Async-compatible**: `execute_tool()` handles both sync and async tool functions
4. **Subprocess isolation**: Atlas runs in its own venv (`.venv_new`) to avoid dependency conflicts
5. **Domain filtering**: Tools can be filtered by 20+ scientific domains
6. **Graceful degradation**: Tools return error strings instead of raising exceptions
