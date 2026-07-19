# A.M.Y/Atlas System Paper: Code, Data, Statistics, Release, and PDF Audit

Date: 2026-07-13  
Classification: exploratory, same-host, read-only audit  
Paper worktree: `.worktrees/amy-system-paper`  
Audited HEAD: `26ab9939cce194540e609cb315772a8b15975a05`  
Machine-readable record: `AMY_SYSTEM_PAPER_DEEP_AUDIT_RAW_2026-07-13.json`  
Replay validation: `AMY_SYSTEM_PAPER_DEEP_AUDIT_VALIDATION_2026-07-13.json`

## Decision

The paper is useful as **exploratory design evidence**, but it is not suitable
as confirmatory evidence for the new study and is not ready to be cited as an
authenticated, independently reproducible scientific release.

This decision does not mean that every result is wrong. The committed release
is internally digest-consistent, all 540 stored scores reproduce under an
independent reimplementation of the deterministic scorer, and the manuscript
reports its primary null result rather than hiding it. The blocking problems
are narrower and verifiable: the current revision is unsealed; the one positive
secondary result is not robust to the dependence structure; the executable
analysis was not frozen before response collection; the registration and
release are unauthenticated local records; and the retained Ollama artifacts do
not identify an immutable model or preserve byte-exact HTTP exchanges.

## Snapshot separation

| Object | Observation | Permitted interpretation |
|---|---:|---|
| Committed release at `26ab993...` | 1,148/1,148 `MANIFEST.sha256` entries match; 1,146/1,146 payload entries match | Internally digest-consistent Git commit bytes |
| Current paper worktree | 13 manifest mismatches in both release manifests | Unsealed revision; not a valid release |
| Current changed paper formats | MD `b2e4806d...`; TeX `e1b2d186...`; PDF `1a4dc8c...` | These bytes are not the bytes named by the existing manifests or `verification.json` |
| Existing verification record | Names PDF `34df8dcb...` | Correct for committed HEAD, stale for the current worktree |
| Release authentication | No signature, Sigstore bundle, authenticated tag, or signed commit observed | SHA-256 integrity only; no authenticated publisher identity or trusted time |

The 13 current mismatches are the five figure PDFs, five figure SVGs, and the
MD, TeX, and PDF manuscript files. The five PNG figures remain the committed
bytes. The report therefore does not label the historical commit “corrupt” and
does not label the current differences malicious.

## Findings

### SP01 — The current revision is not a release

The current manuscript and vector figures were edited after the committed
release, while `MANIFEST.sha256`, `PAYLOAD_MANIFEST.sha256`, and
`verification.json` were not regenerated. Until review is complete, that is an
ordinary working state; it must not be presented as a verified package. A new
version must receive new manifests and a new authenticated release identity.

### SP02 — The reported secondary “improvement” is dependence-sensitive

The paper reports unsupported-decimal rates of 37.8% for `hash_only` and 20.0%
for `full`. Recalculation from `benchmark/runs.jsonl` reproduces the published
pair-level exact McNemar p-value (`9.063271916964766e-06`) and Holm-adjusted
p-value (`4.531635958482383e-05`). Those calculations treat 180 case-seed pairs
as the inferential rows.

The data contain only 18 cases and six unique evidence packets. Ten seeds are
repeated model samples within each case, and all three cases in a domain share
the same evidence bytes. Unregistered but necessary dependence sensitivities
give:

| Analysis level | Clusters | Full minus hash-only | Exact two-sided sign-flip p |
|---|---:|---:|---:|
| Pair level, published | 180 pairs | -0.1778 | `9.063e-06` before Holm |
| Case level | 18 cases | -0.1778 | `0.0703125` |
| Domain/evidence-packet level | 6 domains | -0.1778 | `0.1875` |

The direction remains favorable descriptively, but “improves” is too strong.
The defensible wording is: **a pair-level exploratory reduction was observed;
case- and domain-cluster sensitivities were inconclusive**. The primary
false-support endpoint remains a floor-effect null: 0/60 versus 0/60,
risk difference 0, McNemar p=1. It supports the preregistered decision that the
primary hypothesis was not supported; it does not establish equivalence.

### SP03 — Methods were declared, but executable analysis was not frozen first

The local chronology is:

| Event | Local time normalized to UTC |
|---|---|
| Preregistration commit `1359bd4...` | 2026-07-09 06:48:24Z |
| Runner commit `45d058c...` | 2026-07-09 06:49:11Z |
| Production start in protocol record | 2026-07-09 06:53:25Z |
| First retained provider response | 2026-07-09 06:54:10Z |
| First analysis-code commit `20bb65d...` | 2026-07-09 06:56:21Z |
| Benchmark completion | 2026-07-09 07:24:09Z |
| Results/analysis commit `d16ac1e...` | 2026-07-09 07:28:03Z |

The JSON preregistration did declare McNemar, the paired risk difference,
bootstrap settings, Holm correction, stratification, and sensitivities. The
scorer and runner were committed before production. However, the first
executable analysis implementation was committed 131 seconds after the first
retained response, and it changed several times while collection continued.
The observed history does not prove outcome-adaptive manipulation, and the core
published methods agree with the prior JSON. It does mean that a claim of a
fully frozen executable analysis is false. The new study must freeze and hash
the actual analysis program and tests before the first confirmatory byte is
collected.

### SP04 — The preregistration establishes local ordering, not trusted priority

The unsigned Git commit precedes the protocol start, but no OSF registration,
public read-only registry, signature, transparency timestamp, or external
witness was observed. `verification.json` declares
`registered_utc=2026-07-09T00:00:00Z`; that value is self-reported and is not
the Git commit time. The paper may say “locally preregistered in Git before the
run,” but not imply an independently trusted public preregistration.

### SP05 — The Ollama record is auditable output, not an exact model replay

The package contains 540 intended request objects and 540 parsed API response
objects. All response contents are byte-distinct, all responses report the
alias `glm-5.2`, and all 540 stored scores recompute. These are real strengths.

The retained request object omits the effective `max_tokens=700` option passed
by the runner. Neither side stores exact HTTP body bytes, HTTP headers, status,
provider request ID, attempt number, server version, immutable model digest or
revision, or an echoed seed. The client calls `response.json()` and the runner
serializes the resulting Python object with sorted keys and indentation. The
artifacts are therefore **parsed and reserialized API JSON**, not raw HTTP
exchanges. A hosted-model rerun is a replication against a potentially changed
service, not exact reproduction of the July 2026 computation.

### SP06 — Generation integrity has resumability and failover gaps

Static inspection of the exact runner/scorer/client tree named by the protocol
found:

- when `evidence/index.json` already exists, evidence output is reused after
  required-marker checks, without recomputing its stored SHA-256 or checking the
  provenance output digest;
- resumed rows are trusted by `run_id`; their linked request/response bytes,
  case fields, and scores are not revalidated before the row is skipped;
- a missing or blank response model name is accepted, and nonblank model names
  are compared only before the first colon;
- dual-key failover does not preserve attempt-level failures when a later
  attempt succeeds;
- final manifests protect the committed package after generation, but they do
  not retroactively prove that every intermediate decision used the intended
  bytes.

The retained package happens to pass fresh evidence, request, response, and
score checks. The findings are latent chain-of-custody defects, not evidence
that this dataset was altered.

### SP07 — Deterministic scoring is reproducible but not validated ground truth

Independent reimplementation reproduced all 540 stored score objects. The
measurement still has construct-validity limits:

- expected relations are investigator-authored contracts, not independently
  annotated labels;
- the decimal detector ignores integers and does not bind a number to its unit,
  quantity, or sentence context;
- any output decimal numerically close to any evidence decimal can be accepted,
  even if used for a different quantity;
- prohibited claims use case-authored exact substring matching;
- one response returned `limitations` as a JSON list and was silently coerced
  to a Python string instead of failing strict schema validation;
- 27/540 abstracts and 22/540 conclusions violate the prompted word ranges,
  but those constraints are not scored or enforced.

The endpoints are useful engineering indicators. They are not a validated
measure of scientific truth or manuscript quality.

### SP08 — “Immutable raw responses” is not supported

The manuscript's contribution list uses “immutable raw responses.” The
committed artifacts are content-bound by unsigned manifests, but the package
has no authenticated immutable archive identity and the response files are
normalized JSON objects. Replace the phrase with **manifest-bound retained API
response objects**. “Raw model output text” is acceptable only when explicitly
distinguished from byte-exact transport data.

### SP09 — The release is not independently discoverable or reproduced

The Data Availability section names only paths relative to a local release. No
version DOI, concept DOI, OSF registration URL, public immutable release URL, or
independent reproduction record was observed. The release also does not contain
the analysis source itself; it relies on a referenced repository commit.

### SP10 — The PDF is readable but not archival-quality or byte-reproducible

Visual inspection of all seven rendered pages found no clipping, overlap, or
unreadable table. The PDF is Letter-sized and internally coherent. Remaining
issues are:

- it is untagged and the standard Type 1 fonts are not embedded;
- “A.M.Y/Atlas Project” is the sole author string, with no accountable human
  authors or contribution statement;
- citation keys are printed directly rather than rendered in a publication
  style;
- figures appear in visual order 1, 2, 4, 3, 5;
- the all-zero primary chart occupies most of a page and shows marginal Wilson
  intervals that do not represent case/domain clustering;
- the reference page has substantial unused space;
- the ReportLab builder does not set invariant output. Two same-input builds
  one second apart under Python 3.12.13 and ReportLab 4.4.9 produced different
  PDF hashes (`3be7fe20...` and `a28af38c...`) while extracted text was identical
  (`b9dfda63...`). Creation timestamps and document IDs differ.

## What can be retained

The following components are worth preserving as exploratory or design input:

1. the explicit primary falsification rule and visible null result;
2. the 18-case/three-arm structure as a pilot fixture, not a confirmatory
   denominator;
3. the complete request/response/score ledger;
4. the distinction between hash integrity and scientific truth;
5. the disclosure that six evidence packets underlie 18 cases;
6. the historical corpus/tool-coverage debt as motivation, after rerunning it
   against a frozen source snapshot;
7. the responsible-use and hosted-model-drift limitations.

The following claims must not be inherited by the new paper:

- a robust full-policy improvement;
- immutable or authenticated raw responses;
- exact reproducibility of a hosted alias;
- independent or public preregistration;
- externally validated scientific labels;
- archival release quality or independent reproduction.

## Required corrections in the new study

1. Freeze protocol, cases, labels, scorer, analysis code, tests, environment,
   and expected decision rules before any confirmatory run.
2. Register that complete hash inventory in a public time-stamped read-only
   registry.
3. Use case or evidence-packet/domain as the inferential cluster; treat model
   seeds as within-cluster repeated calls.
4. Obtain blinded, independent annotation and adjudication for scientific
   relation labels and scorer validity.
5. Persist exact outbound payload bytes, normalized semantic request, exact
   response body bytes, safe response headers, status, request IDs, every
   retry/failover event, effective options, and errors.
6. Record client/server versions and the strongest provider model identity
   available. If weights/backend remain opaque, say replication rather than
   exact reproduction.
7. Recompute evidence and provenance digests before every reuse and validate all
   resumed rows before skipping them.
8. Generate deterministic accessible PDF/A-style output with embedded fonts,
   tagged structure where feasible, fixed metadata, and a clean-room rebuild
   comparison.
9. Publish a signed/attested versioned release and a version DOI; never update
   identified bytes in place.
10. Require independent artifact review and domain-expert review before any
    confirmatory claim is promoted into the manuscript.

## Reproduction commands

From `experiments/verifiable_release_study`:

```bash
uv run --frozen python scripts/audit_system_paper_integrity.py
uv run --frozen python scripts/validate_system_paper_audit.py
uv run --frozen pytest -q tests/test_system_paper_integrity_audit.py
```

The retained validation reports scanner SHA-256
`d160503d8d2e9f10e8285849c2f00d24c482ecf11829e68d762673bf7b866370`
and canonical audit SHA-256
`aa9ec157617b9d6eb7e85fee873803004b5e3748a063464c90913b0ff27a6673`.

## Boundaries

This is not an independent replication, a cryptographic attribution of the
authors, or a domain-expert judgment of the six scientific computations. It
does not infer misconduct from chronology, dirty files, or unsigned artifacts.
It establishes only what the retained bytes, Git objects, deterministic
recalculation, source inspection, and PDF rendering support.
