# AXIOM Deep Code, Artifact, and Paper-Evidence Audit

Date: 2026-07-13  
Classification: exploratory, same-host, static/read-only audit  
Machine record: `AXIOM_DEEP_AUDIT_RAW_2026-07-13.json`  
Replay record: `AXIOM_DEEP_AUDIT_VALIDATION_2026-07-13.json`

## Decision

No retained AXIOM manuscript or capability summary should be used as scientific
evidence for the new paper. AXIOM is observable in this snapshot primarily as
the package/project brand `axiom-atlas` and as class/demo labels over Atlas
source. The scan found no separate top-level `axiom` Python package, console
entry point, or `/axiom` route literal. This does not prove that AXIOM never
existed in another revision or deployment; it defines the audited boundary.

The retained AXIOM material is still valuable in two ways: as negative evidence
about the current system's evidence discipline, and as a source of adversarial
test cases for the new verifiable-release study. It is not a basis for claims of
autonomous discovery, real-data validation, independent peer review, production
readiness, or measured performance gains.

## Audited boundary

| Layer | Observation |
|---|---|
| Package | `axiom-atlas` 4.1.0, classifier `Development Status :: 3 - Alpha` |
| Install surface | `app*` and `scripts*`; zero console entry points |
| Independent AXIOM surface | No top-level `axiom/`, no `/axiom` route literal, 13 AXIOM-named classes in Atlas/app/scripts/examples |
| HTTP identity | Two FastAPI applications titled `A.M.Y API`, versions `2.0.0` and `4.1` |
| Docker entry | `main:app` |
| Static Python scope | 1,676 files under `atlas/*.py`, `app`, `scripts`, and `examples`; 23 parse failures |
| Deployment blocker | Both app entry modules import `app.middleware.setup`; that module has a `SyntaxError` at line 29 |
| Container identity | Zero Docker/Compose images pinned by digest; three explicit `:latest` images |

The scanner did not import Atlas, run a service, make network calls, load model
files, or read credential values. The Docker finding is therefore a direct
static startup blocker, not a runtime availability measurement.

## Findings

### AX01 — AXIOM is not a separately evidenced executable system here

The project name and prose frequently say AXIOM, while the deployed API identity
is A.M.Y and the executable modules are Atlas/app code. A paper must define
these names operationally:

- **A.M.Y**: controller/research pipeline under test;
- **Atlas**: executable tool/service layer actually invoked;
- **AXIOM**: package/project or experimental program label unless a separate,
  hashed executable boundary is supplied.

Treating all three as interchangeable would make version, failure, and evidence
claims unfalsifiable.

### AX02 — The declared production entry has a direct syntax blocker

`atlas/main.py` and `atlas/app/main.py` both directly import
`atlas/app/middleware/setup.py`, whose current bytes have SHA-256
`a830a61b2b9214394752c7c937f752c2ed8942ded14bab1b439dcaff80bc1a7b`
and fail parsing at line 29. The configured Docker entry is `main:app`.
Consequently, current production-start claims require a new clean-build run;
documentation or previous status output cannot establish that these bytes boot.

### AX03 — Health and performance endpoints return claims, not measurements

The root health endpoint returns literal `healthy` and version `2.0.0`. The
detailed status endpoint hard-codes four modules as `active` and reports
estimated startup, memory, and concurrent-user values. The metrics endpoint
returns `60-80%` startup reduction, `40-60%` memory reduction, and `2-3x`
development speed without a linked benchmark. Startup catches a general service
initialization exception and continues. These values may describe goals or old
observations, but the current endpoint implementation is not measurement
evidence.

### AX04 — None of the scientific/claim artifacts has a verifiable chain

Fourteen AXIOM-named JSON files parsed successfully. Eleven were classified as
scientific/demo outputs or capability claims. Across those eleven, the scanner
found zero artifacts with:

- authentication/signature fields;
- content-digest fields;
- source revision;
- dependency identity;
- immutable model identity;
- seed;
- provenance;
- raw request/response exchange fields.

Twelve of the fourteen files are Git-ignored, two are tracked, and four have no
identified producer. Auditor-computed hashes identify present bytes only; they
do not recover origin, historical time, or authorization.

### AX05 — A final assessment contradicts three failed upstream states

In `atlas/artifacts/demos/axiom_complete_demo_20250921_213324.json` (SHA-256
`6160a8cf...`), hypothesis generation, research-cycle completion, and tool
corroboration each have upstream `success=false`, while the final assessment
sets the corresponding claim to `true`. Its DFT validation is not linked to an
executable record, and the named MIT/Stanford/Berkeley reviewers are
unauthenticated strings. This is an internal consistency failure, not peer
review or computational validation.

### AX06 — Two positive astronomy reports contain zero queried data

`axiom_demo_report_20250925_005737.json` and
`axiom_demo_report_20250925_005837.json` each report zero queries, zero
successful connections, and zero analyzed objects, yet repeat four positive
findings about verified stellar parameters, confirmed exoplanets, catalog
cross-correlation, and real-time analysis. These findings cannot be cited as
observed results.

### AX07 — The “comprehensive real data” demo is source-embedded simulation

For `axiom_real_data_comprehensive_demo.json`, the scanner identified
`atlas/scripts/experiments/axiom_real_data_demo.py` as producer. That source
contains zero network calls and zero random calls in the audited producer,
twenty-two artifact subtrees exactly match source literals, and the complete
`real_data_examples` object equals the producer's returned literal. The source
explicitly calls its peer-review block a simulation.

This does not imply fabrication of an external experiment. It establishes that
the artifact is a deterministic demonstration over embedded examples and
simulated outputs. The words “real data,” “peer review,” and “autonomous” must
not be promoted into empirical claims.

### AX08 — Astronomy mixes network connectors and embedded catalogs without raw evidence

The retained astronomy report declares seven data sources. The connector has
three network-backed methods and four source-embedded catalog methods. The
report's `analysis_results` is empty, it retains no raw API response or digest,
and its producer sets `real_data_verification=true` unconditionally. The
scientific workflow's 50% habitability rate is simply 2/4 for an embedded
four-planet sample. Neither artifact supports a population estimate or a
reproducible external-data result.

### AX09 — The autonomous HF report cannot identify the models it used

`axiom_autonomous_research_report_hf.json` records five workflow steps and
labels `codellama:7b`, `llama3:8b`, `mistral:7b`, and `qwen:7b` as
`huggingface`. It stores prompt/response lengths rather than complete exchanges
and has no endpoint, revision, weights digest, seed, source revision, or
authentication fields. Provider labels and generated text are inspectable;
immutable attribution and bitwise replay are not possible.

### AX10 — Capability-summary language is unsupported

`axiom_complete_analysis_summary.json` has no identified producer, provenance,
or content digest. It calls AXIOM “revolutionary and fully functional” and
asserts 100x discovery acceleration, patent-ready catalyst candidates,
automatic Nature/Science papers, and multi-method DFT/literature validation.
No retained artifact in the audited chain supplies the experiments, denominators,
comparators, executions, or external reviews required for those claims.

## Implications for the new paper

The new manuscript may cite this audit only for bounded observations about the
audited snapshot. It must not cite the AXIOM demos as positive scientific
results. A defensible sentence is:

> In a read-only audit of the current AXIOM/Atlas snapshot, retained demo and
> capability artifacts lacked authenticated provenance and included internal
> contradictions, embedded-data simulations presented with “real data” labels,
> and positive findings without queried objects.

That sentence still needs the exact snapshot, scanner hash, raw JSON, and replay
record in the released evidence ledger.

## Required remediation before any AXIOM claim

1. Define a separate AXIOM executable and version boundary, or state explicitly
   that AXIOM is the program/package name over Atlas.
2. Restore a parseable clean deployment and retain the build/start/health logs.
3. Replace literal health/performance claims with measured probes linked to raw
   records and explicit denominators.
4. Give every experiment an immutable source revision, complete input digest,
   dependency/container identity, seed, command, output digest, and producer.
5. Archive external request and response bytes plus source/version/license
   metadata; label embedded catalogs and simulations as fixtures.
6. Make final assessments fail closed when an upstream required stage fails.
7. Remove institutional reviewer names unless actual reviewers consent and
   their review records are authenticated and disclosed.
8. Ban “revolutionary,” “100x,” “patent-ready,” and publication-readiness claims
   until preregistered comparisons and external review support them.
9. Separate model provider, model family, exact revision/digest, endpoint,
   parameters, seed, and full exchange records.
10. Obtain independent domain review and clean-environment reproduction before
    any scientific result enters the paper.

## Reproduction

From `experiments/verifiable_release_study`:

```bash
uv run --frozen python scripts/audit_axiom_integrity.py
uv run --frozen python scripts/validate_axiom_audit.py
uv run --frozen pytest -q tests/test_axiom_integrity_audit.py
```

The retained validation is valid and reports:

- scanner SHA-256:
  `f7bb62b773e65d7797ca274d58884e5f0ddec42f08cbbe61ae3cafddfef07db6`;
- pretty JSON SHA-256:
  `6cf3f6911bcc267a00b40d611f0023a639571d7b8620cb73719d12b9c539f2ea`;
- retained and fresh canonical SHA-256:
  `a5fcb2b79a73c71840889aa90a3f22db28d7f72f52d05991b1178113ae01e74c`.

## Boundaries

The audit does not execute producers, query external services, recover a 2025
environment, establish historical intent, or decide whether any embedded value
is factually correct. It separates present-byte integrity, authentication,
reproducibility, and scientific truth; none is inferred from the others.
