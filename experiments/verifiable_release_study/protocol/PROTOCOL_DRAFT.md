# Protocol Draft

Protocol version: `0.3.0-draft`  
Prepared: 2026-07-13  
Status: exploratory design; not preregistered; not frozen

## 1. Objective

Evaluate four concrete release-verification profiles against a frozen corpus of
clean and adversarial scientific release packages. The study asks two separate
questions:

1. **Implementation conformance:** does each verifier implement its own frozen
   profile correctly?
2. **Target acceptance coverage:** which invalid packages are still accepted by
   each partial profile relative to the study's frozen target release contract?

The first question uses profile-specific expected decisions. The second uses one
profile-independent target decision. Neither establishes scientific truth.

## 2. Intended contributions

1. A precise decomposition of existence checks, payload checksums, signature
   authentication, and provenance-policy verification.
2. A machine-readable adversarial corpus with exact changed bytes, structural
   applicability, decisions, and reason codes.
3. A fail-closed reference verifier for an attested scientific release.
4. A code-and-artifact-grounded A.M.Y/Atlas case study, including working
   controls and negative findings.
5. An artifact package that another team can exercise from case generation to
   paper tables and figures.

The project does not propose a cryptographic primitive and will not present
standards composition as cryptographic novelty.

## 3. Study layers

- **L0 — Exploratory baseline audit:** current A.M.Y/Atlas code and artifacts;
  disclosed but excluded from confirmatory counts.
- **L1 — Mechanism analysis:** standards-grounded capability and limitation
  matrix for each profile.
- **L2 — Confirmatory finite benchmark:** frozen packages, mutation operators,
  expected decisions, and verifier outputs.
- **L3 — Reproduction:** the same frozen benchmark in a clean environment and,
  when an external-reproduction claim is made, by a person not involved in
  verifier implementation.

## 4. Research questions

- **RQ1:** Within the frozen catalog, which observed partial mechanisms accept
  altered payload bytes, coherently replaced manifests, or unauthorized release
  identities?
- **RQ2:** Does each reference verifier match its own frozen decision contract on
  every structurally applicable case?
- **RQ3:** Within the frozen corpus, which target-invalid cases does each profile
  accept, reported case by case and by attack family?
- **RQ4:** Does the integrated profile bind exact manifest bytes to an authorized
  identity and SLSA provenance while independently checking every referenced
  payload?
- **RQ5:** Are decisions and primary reason codes identical in the author and
  clean reproduction environments?
- **Exploratory case-study question E-RQ6:** Which current A.M.Y/Atlas claims and
  controls are supported, narrowed, or contradicted by code and artifact
  evidence already inspected during design?

There is no hypothesis that a profile will pass because its oracle says it
should. Unexpected results remain results and cannot be deleted or relabeled.
E-RQ6 is reported outside the confirmatory block. It can become confirmatory
only in a future preregistered study over a genuinely held-out snapshot.

## 5. Common release object

The benchmark input is a release directory containing:

```text
MANIFEST.jcs.json
attestation.sigstore.json
payload/...
```

- `MANIFEST.jcs.json` is an RFC 8785 JCS representation that lists the
  closed-world payload inventory, semantic roles, byte sizes, and full SHA-256
  digests. It contains no signature and no self-hash field.
- The authenticated in-toto Statement subject is the SHA-256 of the **exact
  manifest bytes**.
- `attestation.sigstore.json` is one frozen Sigstore bundle containing one DSSE
  envelope; the envelope payload is the authenticated in-toto Statement. There
  is no detached duplicate provenance object used as verifier input.
- The P3 predicate type is exactly `https://slsa.dev/provenance/v1`.
- Payload files, the manifest, and attestation sidecars are separate objects, so
  no file is required to hash or sign itself.
- Published transport archives are separately identified by SHA-256. Safe
  archive extraction is an ingestion concern and will not be conflated with
  directory-manifest verification.

The retained synthetic pilot uses the historical v0.1
`schemas/manifest.schema.json`. The selected production profile uses the
separate v0.2 `schemas/manifest-production-v0.2.schema.json`, which requires an
explicit `build_metadata` object. This preserves old pilot interpretation while
preventing a schema migration from silently changing retained bytes. Both use
`protocol/PATH_POLICY_DRAFT.md` and `rfc8785==0.1.4`.
The retained GitHub-attestation v1 policy, result schema, CLI, cryptographic
core, and real-P2 smoke likewise remain byte-identical historical artifacts.
The current production line is v2: its policy has a closed schema, exact
policy-schema and result-schema digests, and an explicit non-runnable template
state. Verification requires an expected policy SHA-256 from the external R0
identity before those policy bytes may authorize a bundle. Every structured v2
decision then carries the policy, policy-schema, and result-schema SHA-256
values; if that complete contract cannot be established, the CLI emits no JSON.
The controlled selected-profile S1 layer now has a parseable deterministic
USTAR snapshot, six clean migrated bases, a 41-case v0.4 draft catalog, eleven
implemented changed semantic mutations, and a separately validated 246-row
compatibility product. These are controlled-public-PKI contract checks, not
production Sigstore or confirmatory outcomes. `TBD-BEFORE-REGISTRATION`:
complete and independently review the full 41-case selected-profile generator
and oracle, freeze exact contract bytes, the DSSE/Sigstore bundle schema/tool
version, and transport archive format.

## 6. Verification profiles

All profiles return `ACCEPT`, `REJECT`, or `ERROR`, with one primary reason code
and zero or more secondary codes. `ERROR` means the verifier failed to produce a
policy decision; it never satisfies an expected `REJECT`.

Per-check output uses `PASS`, `FAIL`, `NOT_RUN`, or `NOT_REQUIRED`. A profile that
does not include a check reports `NOT_REQUIRED`; a check skipped after an earlier
terminal failure reports `NOT_RUN`. Neither is encoded as boolean `false`, so an
independent reader can distinguish failure from deliberate omission and
short-circuiting.

Before profile-specific checks, the verifier performs a bounded directory
preflight using non-following metadata inspection. It counts entries and declared
byte sizes without hashing payload content, enforces the draft/frozen package
limits, and does not treat an observed file as trusted merely because it was
enumerated. Confirmatory cases are verified from private per-case snapshots;
profile implementations must open files without following links where supported
and compare file metadata before and after reading to detect concurrent changes.

### P0-METADATA

- requires `MANIFEST.jcs.json` to exist and remain below the fixed manifest size
  limit;
- parses that manifest as JSON and rejects malformed JSON;
- uses the frozen ordinary JSON parser behavior for P0, under which duplicate
  object names are accepted and the last occurrence is retained; P0 deliberately
  does not perform the strict duplicate-name check used by P1/P3;
- may read stored status fields;
- does not validate manifest schema, paths, roles, inventory, sizes, digests,
  signatures, signer identity, or provenance semantics.

This models existence/syntax/self-report behavior. It is intentionally weak and
is specified exactly so its oracle is not invented per case.

### P1-CHECKSUM

- includes bounded input parsing;
- requires canonical JCS manifest bytes and validates the frozen schema;
- rejects duplicate JSON keys and duplicate normalized paths;
- requires portable relative paths and forbids symlinks/path escape;
- requires listed payloads to be regular files with one link and rejects
  symbolic links, hard links, devices, sockets, and FIFOs;
- enforces required roles and a closed-world payload inventory;
- streams and recomputes full SHA-256 and byte size for every payload;
- ignores signatures and does not authenticate the manifest author, builder, or
  source revision.

### P2-SIGNATURE_ONLY

- authorizes the exact trust policy by comparing its raw bytes to the external
  expected SHA-256 before interpreting the bundle;
- reads a bounded DSSE/Sigstore bundle;
- validates the outer bundle structure, verifies the DSSE signature before
  treating its payload as trusted, and only then parses the authenticated
  Statement needed for subject extraction;
- cryptographically verifies the envelope and required public transparency
  evidence under the frozen trust roots;
- enforces the frozen issuer, repository, workflow/ref identity, and approved
  algorithm policy;
- verifies that the authenticated Statement subject equals the SHA-256 of the
  exact manifest bytes, computed over the raw file octets exactly as read;
- does not parse, normalize, canonicalize, or reserialize the manifest before
  computing that subject digest;
- deliberately does **not** validate the manifest schema, canonicalization,
  paths, roles, inventory, or any referenced payload bytes;
- deliberately does **not** enforce the SLSA predicate semantics.

This ablation isolates authentication from artifact verification. The current
Atlas signature verifier is analyzed as a local, weaker instance of this pattern
because it authenticates manifest bytes but does not validate the referenced
artifacts in the same gate.

### P3-ATTESTED_RELEASE

Includes every P1 and P2 check and additionally:

- requires in-toto Statement v1 with predicate type
  `https://slsa.dev/provenance/v1`;
- enforces the standard `actions/attest` default-provenance build type, exact
  workflow, builder, source dependency, repository, ref, and full source
  revision;
- parses the authenticated v0.2 manifest only after subject binding and checks
  its explicitly labeled workflow-authored `build_metadata`;
- rejects official manifests declaring a dirty source and enforces the frozen
  Git tree, opaque source-snapshot digest, dependency-lock, and execution-image
  identities;
- cross-binds the source snapshot and dependency lock to manifest payload
  entries before P1 recomputes their current bytes;
- produces stable, machine-readable reason codes for every rejection.

GitHub/Sigstore derives the certificate identity and authenticates the exact
manifest subject. The workflow authors the clean/tree/snapshot/lock/image
values. Authentication proves that the authorized workflow asserted those
values, not that GitHub independently measured or certified their truth. P3
hashes the exact snapshot file but does not inspect its tar members or claim
that they reconstruct the workflow-authored Git tree.

P3 does not claim stateful rollback protection in the primary study. A signed old
release remains valid unless a verifier receives trusted freshness state. Exact
version DOI/digest selection is part of release identity, not a hidden promise
that signatures alone prevent replay.

## 7. Target release contract and two decision labels

The frozen target contract requires:

- safe bounded inputs;
- canonical/schema-valid manifest;
- closed-world complete inventory;
- exact payload size and SHA-256;
- authenticated manifest subject;
- authorized public release identity and transparency evidence;
- required SLSA source, builder, and material policy;
- clean acceptance in supported environments.

This target contract is an author-defined normative acceptance policy grounded
in the cited standards and independently reviewed before registration. It is not
an observed law of nature, an empirical ground truth about every attack, or a
claim that P3 prevents threats explicitly placed outside the contract.

Every catalog case contains:

1. `target_decision`: whether a release satisfying this target contract must be
   accepted or rejected;
2. `profile_expectations`: what P0–P3 should do if implemented exactly;
3. `prerequisites`: structural requirements used to build the compatibility
   matrix, independent of expected outcomes;
4. the exact mutation and expected primary reason code.

Example: after coherent payload-plus-manifest replacement, P1 is expected to
`ACCEPT` because it has no authenticated manifest. That is correct P1
implementation behavior and simultaneously a miss relative to the target
contract. It is not mislabeled as a P1 software bug.

## 8. Design requirements and falsification conditions

- **D1 — Content binding:** P1 and P3 must reject changed referenced payload
  bytes under an unchanged manifest. Acceptance falsifies their content-binding
  implementation.
- **D2 — Authentication binding:** P2 and P3 must reject a changed manifest under
  the original valid attestation. Acceptance falsifies subject binding.
- **D3 — Complementarity:** P2 is expected to accept altered payload bytes when
  signed manifest bytes are unchanged; P1 is expected to accept a coherently
  replaced unauthenticated manifest. These are intentional ablation boundaries.
- **D4 — Provenance policy:** P3 must reject a wrong authenticated predicate,
  workflow/builder/source dependency, or authenticated manifest metadata for
  source revision/tree/dirty state, source snapshot, dependency lock, and
  execution image. Snapshot mutation is tested as exact-byte binding; no
  tree-to-tar semantic-equivalence target is defined.
- **D5 — Clean behavior:** every profile must accept every clean package that
  satisfies its frozen input profile. Rejection cannot be repaired by post hoc
  “incompatibility” relabeling.
- **D6 — Cross-environment determinism:** terminal decision and primary reason
  code must match across required environments for identical case bytes and
  trust-policy bytes.

These are system requirements and falsification rules, not probabilistic claims
about an unobserved population of attacks.

## 9. Units and corpus

The atomic unit is **base release bundle × one compatible mutation operator**.
Repeating a deterministic verifier on identical bytes does not add an independent
unit.

The current draft S1 registry contains six structurally distinct, entirely
study-generated CC0 base blueprints:

1. table, deterministic analysis, nested result, figure, and zero-byte control;
2. manuscript source, valid minimal PDF, figure, lock, and evidence ledger;
3. deterministic binary model larger than two hashing chunks plus metadata;
4. nested source, configuration, and environment lock;
5. authored opaque-model request/response fixture with explicit non-reproducible
   backend semantics;
6. mixed research release with deep paths and a >1 MiB output.

They are S1 conformance fixtures, not historical A.M.Y/Atlas outputs. The real
A.M.Y release-specific GitHub/Sigstore object belongs to separate S2 and remains
unresolved. The retained base pilot generated no mutation cases; its first
schema-invalid result attempt remains public and a second attempt passed a
separate validator and same-environment deterministic replay.
The separate selected-profile R0 run preserves every blueprint byte, injects
only two collision-free provenance fixtures, validates a real deterministic
USTAR snapshot, and replays P0–P3 over all six bases. Its 24 clean results are
`ACCEPT/OK`; this establishes controlled fixture availability only and is not a
confirmatory clean-acceptance result. A later replay keeps the retained archive,
manifests, payloads, and 24 decisions internally valid but reports that three
source paths now differ from that run's archived source snapshot. The old run is
therefore historical evidence, not a claim that it embeds the current code.

Compatibility is based only on mutation prerequisites. For example, a bit-flip
requires a non-empty regular payload; a wrong-source case requires the selected
source-dependency plus authenticated-manifest-metadata structure. It may not
depend on whether a profile is expected to pass.

The historical v0.3 product remains immutable at 204 rows. The selected-profile
v0.4 draft product is the complete 6 × 41 Cartesian set: 185 `COMPATIBLE`, 54
`PENDING`, and 7 `NOT_COMPATIBLE`. Retained, hash-bound probes in both planned
environments resolve filesystem capability. The 54 pending rows correspond to
nine operators whose named policy prerequisites are not frozen; none is
silently counted as compatible. Six non-compatible rows are public-keyless
transparency cases that belong to production S2, not controlled-PKI S1. The
seventh is `B04-SOFTWARE × INVENTORY-OMIT-ROLE-001`: the base has more than one
payload with the required role, so no unique mutation target exists. The
selected matrix declares its use of clean-base validation but cannot read
mutation outcomes, target decisions, or profile expectations. Its separate
same-worktree validator recomputes every base-derived prerequisite, rebuilds all
246 rows and all mutation plans, and confirms that counterfactually poisoning
every target/expectation field does not change the matrix. Of 246 plans, 245
resolve and the exact B04 row is the sole unavailable plan.

The current pre-registration development implementation has one branch for
each of the 41 selected operators. Temporary generic fixtures exercise all 164
case×profile combinations against the draft expectations, and all 41 mutated
trees replay identically in the author environment. This is defect-finding
evidence only: it neither materializes any of the 246 base×operator candidate
units nor resolves a `PENDING` row. The schema-closed 164-row draft oracle is
rendered only from `cases[].id` and `profile_expectations`, imports no generator,
verifier, or evaluator module, and declares that it read no result. It is still
a same-author artifact, not an independently reviewed oracle.

`TBD-BEFORE-REGISTRATION`: freeze every base, origin/license, base SHA-256,
compatibility row, seed, deterministic generation order, and planned case count
after synthetic pilot testing.

The registration release R0 contains the bases, generator, catalog, oracle,
compatibility matrix, and environment, but not the derived confirmatory case
archives. Those are generated only after registration. Their per-case and
aggregate SHA-256 values belong to evidence release R1. A generation failure is
a retained study failure; it cannot make a planned row disappear as
`NOT_APPLICABLE`.

The machine-readable release-lineage contract separately identifies A.M.Y,
Atlas, AXIOM, and the study toolchain, and forbids using a package version or
the word “latest” as an execution identity. Every frozen stage requires the
exact 18-field identity tuple defined by that contract; the declared Git object
format determines the required OID length. R0 separately records the immutable
registration identifier and the SHA-256 of its externally exported registration
record; a concept DOI is optional and cannot replace either value. R1 must link
the externally recorded SHA-256 of R0 plus its manifest/archive identity. R2 is
an append-only correction chain: every correction has a new archive SHA-256 and
version DOI, immediately names the prior release it supersedes, preserves the
R0/R1 parents, and never replaces prior bytes. At this draft, no such frozen
identity exists: R0 is not frozen and R1/R2 do not exist.

## 10. Oracle construction and review

Mutation generation writes no expected or observed decision. Its future frozen
case record writes:

- parent clean-bundle digest;
- exact pre- and post-mutation file digests;
- changed byte offsets or changed structured fields;

The separate oracle writes:

- target decision and rationale;
- profile expectations derived from the frozen profile text;
- expected reason codes and assumptions.

Some conformance fixtures are intentionally signed by a controlled test identity
that the fixture trust policy marks as authorized. This capability belongs to
the oracle/fixture generator, not to the modeled attacker. It exists so malformed
or semantically invalid authenticated objects can reach the later verifier
checks; it does not assert that an external attacker controls the production
release identity.

The mutation generator, profile implementation, result evaluator, and oracle are
separate modules. Case IDs are opaque during verifier execution. Expected labels
are joined only after all output files are write-locked and hashed.

Before registration, a qualified human who did not implement the verifier,
mutation generator, or analysis and did not author the catalog, oracle
expectations, or propositions must review the exact SHA-bound R0 subject bytes.
The review surface is not limited to the oracle: it comprises all 41 catalog
cases, 164 case×profile oracle rows, twelve propositions, all 246 compatibility
rows, and seven compatibility-policy decisions. The reviewer must not receive
confirmatory outcomes and must have no write access to the subject bytes during
review.

An additional source-bound development check resolves every base-aware plan and
executes 65 target-dependent mutations in disposable copies. Four focused tests
cover target fidelity, collision handling, and forged-plan rejection. This
check invokes no verifier, joins no oracle, writes no result ledger, creates no
confirmatory archive, and reports `NO-GO`.

`scripts/build_r0_review_packet.py` defines the explicit source/contract list,
exact allowlisted base-aware and RG-006 synthetic `NO-GO` receipts, and the
deterministic JCS/USTAR packet. It forbids empirical and confirmatory run
outputs. The
expected manifest and packet
SHA-256 values must reach the reviewer through an authorized channel external
to the packet. A completed record must bind both values and its exact raw bytes
must be detached-authenticated under a separately authorized reviewer-identity
policy. `scripts/verify_r0_review_packet.py` checks only hashes, canonical
manifest/archive mechanics, schema, coverage, and record binding; it does not
verify detached authentication, reviewer authorization or competence, or
scientific truth and cannot close RG-004.

Reviewer identity must be preauthorized before review under
`protocol/R0_REVIEWER_IDENTITY_POLICY_TEMPLATE.json`; it cannot be selected
after seeing the completed record. The current policy is deliberately unusable:
identity, OIDC issuer, authorization record, trusted-root bytes, Cosign version,
platform, and binary SHA-256 are null. A future frozen policy requires exact
identity and issuer strings, an offline trusted root, a pinned binary, no regex
identity matching, no SCT/Tlog bypass, and a version outside the affected ranges
in Cosign advisory GHSA-whqx-f9j3-ch6m. Static policy validation does not execute
Cosign or read a record/bundle.

The current review template is fully populated with `NOT_REVIEWED`, the identity
policy reports `NO-GO`, no reviewer exists,
and RG-004 remains open. Model review can supplement but cannot satisfy this
human-review gate.

## 11. Primary and secondary outcomes

### Primary presentation

- complete case-by-profile observed decision matrix;
- every implementation-conformance mismatch, without aggregation hiding it;
- target-invalid accepts, reported by profile and attack family with exact
  numerator, denominator, and case identifiers;
- clean-package failures by profile and environment;
- cross-environment decision/reason-code disagreements.

The denominator is every planned structurally compatible
`base × mutation-operator` unit. Four profile rows from one unit are paired
observations, not four independent units. Missing generation, missing terminal
execution, and `ERROR` are shown separately and prevent a complete-conformance
claim. Before registration, each RQ is mapped to a proposition, applicable
units, observed field, deterministic decision rule, falsification condition,
and exact permitted claim wording.

The complete draft mapping is machine-readable in
`protocol/PROPOSITION_MATRIX_DRAFT.json`. It defines twelve proposition rows,
explicit planned denominators, treatment of generation/missing/ERROR outcomes,
falsification rules, abstract eligibility, and forbidden extrapolations. It is
not frozen or independently approved yet and therefore does not close the
registration gate.

No pooled “security score,” no macro-averaged headline, and no claim that a
finite-corpus proportion estimates attack prevalence.

### Secondary descriptive outcomes

- primary and secondary reason-code agreement;
- which check first rejected each case under frozen precedence;
- verifier runtime/resource behavior only if a measurement method is frozen
  before registration;
- claim-evidence coverage of the manuscript.

## 12. Analysis

- Publish case-level inputs, outputs, oracle rows, and the exact join operation.
- Present each attack family and case before any descriptive total.
- Keep implementation-conformance failures separate from target-contract misses.
- Treat the catalog as a finite designed benchmark, not a random sample.
- Do not use p-values, confidence intervals, power calculations, bootstrap, or
  deterministic reruns to imply generality the design does not possess.
- If performance is retained, analyze its repeated measurements separately from
  deterministic security decisions and label it exploratory unless preregistered.
- Generate every manuscript number, table, and figure directly from released
  case-level data. Hand-entered result numbers are forbidden.
- Report all unexpected and negative results.

The current dummy analysis is retained as
`dummy_analysis/DUMMY_OBSERVATION_LEDGER.json` and
`dummy_analysis/DUMMY_ANALYSIS_SUMMARY.json`. It covers all 1,480 rows implied
by the present 185 compatible units × four profiles × two primary environments
and injects generation failure, missing execution, `ERROR`, wrong reason,
decision disagreement, and input-hash drift. Before evaluating a proposition,
the analyzer reloads the authoritative catalog, selected compatibility matrix,
and oracle; checks every copied row identifier, base, operator, family, kind,
stratum, target decision, and profile expectation; rejects duplicate
unit/environment/profile cells; requires the exact compatible
unit × environment × profile product; and requires P0–P3 rows for one
unit/environment to share generation state and generated case-archive bytes.

The analyzer keeps all five outcome categories in the denominator. PR-001 is
restricted to S1 as declared. PR-003 and PR-006 are `NOT_EVALUABLE` because the
current observation-ledger v1 does not carry the authenticated observables their
rules require; PR-010 through PR-012 likewise remain `NOT_EVALUABLE` when their
required inputs are absent. PR-008 emits deterministic target-invalid accepts
by profile and attack family, including category counts and exact accepted unit
IDs, and forbids a pooled primary result. The schema fixes
`manuscript_claims_authorized` to `false`; even complete synthetic rows cannot
self-authorize abstract or conclusion language. The current 17-test analysis
suite includes copied-label mutation, duplicate-cell, cross-profile archive and
generation-state mismatch, and relabeling of dummy data as R1. This validates
analysis behavior only; it is not R1 evidence and must be rerun after the final
matrix, environments, review, and R0 bytes are frozen.

## 13. Error and retry rules

- Expected invalid packages must receive `REJECT`, not `ERROR`.
- `ERROR` on a target-invalid package is a target miss and a profile-conformance
  mismatch unless explicitly expected by a frozen profile (the primary catalog
  will not use expected `ERROR`).
- `ERROR` on a clean package is a clean-acceptance failure.
- A verifier crash remains in the data.
- A full rerun is allowed only for exactly one preregistered typed
  infrastructure predicate before any `SCIENTIFIC_INTENT` event or outcome
  exposure; every attempt remains public and the original result is never
  overwritten.
- `NOT_APPLICABLE` belongs only in the frozen compatibility matrix, not in a
  verifier decision.
- `SCIENTIFIC_INTENT` must be durably persisted before spawning a generator or
  verifier. Once present, child return code, signal, duration, crash, timeout,
  output availability, or any other post-intent event cannot authorize retry.
- Attempt two is valid only when it binds the SHA-256 of the already persisted
  attempt-one classification. Invalid, overlapping, late, missing, or
  outcome-exposed classification never authorizes retry.
- Selection is sealed once for `ENV-AUTHOR` and `ENV-LINUX-PINNED` together
  before either environment can release a result for decoding. If an
  environment has no official attempt, every planned row remains in the
  denominator as `MISSING_EXECUTION`; unauthorized attempts are retained but
  never selected.
- A code change after any confirmatory attempt creates a new exploratory lineage
  or a new preregistration. It cannot repair the registered result in place.

The exact current draft is `protocol/RUN_EXECUTION_POLICY_DRAFT.json`. It sets
one execution attempt per case, permits at most one complete-environment rerun
under four source-bound typed predicates, and binds 16 implementation, schema,
test, manifest, and lock inputs by SHA-256. The byte-preserved historical v1
receipt reports 29 passing tests. The v2 receipts retain their historical
52-test states. The active non-overwriting v3 receipt reports 61 passing tests,
including the 12 selection cells; later-attempt retention;
attempt/process consistency; bounded inherited-pipe cleanup and persistent
`EINTR`; exact record-hash recomputation; source-inventory TOCTOU rejection;
injected `ENOSPC`, `EDQUOT`, and `EIO`; same-UID entry substitution detection;
and three process-crash states around no-replace publication. Nine added cells
exercise a canonical parent-hashed local intent chain, process binding,
malformed-log rejection, cooperative locking, failed publication/spawn, and a
crash after intent persistence but before spawn. The active receipt
explicitly limits this fault campaign to atomic JCS publication and establishes
neither power-loss durability, recovery, cross-filesystem equivalence, complete
runner-wide persistence coverage, authenticated intent checkpoints, rollback
detection, same-UID exclusion, classifier derivation, production isolation, nor confirmatory
execution. Its retained validation is internally valid but reports `NO-GO`: 11 RG-006 controls
and 54 compatibility rows remain open, the dummy analysis is not frozen, and
qualified external human review/R0 freeze have not occurred. The complete
state machine and limitations are in
`protocol/CONFIRMATORY_RUNNER_CONTRACT_DRAFT.md`.

## 14. Pilot and stopping rule

Pilots use synthetic packages excluded from confirmatory results. Pilots may
change the draft profile, catalog, schema, reason codes, or implementation.

The separate `S0-ENGINEERING-ROBUSTNESS` stratum schedules temporal mutation
and injected infrastructure failures before registration. Its 12 tests are not
attack-catalog units and never enter primary denominators. Input mutation must
terminate as `REJECT/INPUT_CHANGED`; injected I/O, policy/schema, crypto-backend,
or verifier-timeout failures must terminate as `ERROR/INTERNAL_ERROR` and are
never counted as successful rejection. The retained author and pinned-Linux
runs establish only the scheduled interleavings on those environments, not
freedom from all filesystem races.

After pilot:

1. freeze and hash all profiles, schemas, catalog, compatibility matrix, oracle,
   bases, seeds, code, analysis, trust policy, and dependency lock;
2. complete independent oracle review;
3. register the complete design before confirmatory package generation or
   verifier execution;
4. run every frozen compatible case exactly once per required environment;
5. stop only when every planned case has a terminal retained result or retained
   terminal generation/infrastructure failure under the frozen rules.

The run never stops based on favorable results or manuscript scores.

## 15. Reproduction environments

At minimum:

- recorded author environment;
- fresh Linux CI environment from a pinned image digest;
- independent execution of the complete frozen benchmark by a qualified
  person/service before manuscript submission. This is mandatory for this
  study, not an optional wording upgrade. Until a signed, dated external
  execution record exists, claim C011 remains prohibited and the manuscript
  is not submission-ready.

Record OS, architecture, Python, verifier version, source commit and source
snapshot SHA-256, lockfile, image digest, locale, timezone, trust-policy digest,
policy-schema digest, terminal-result-schema digest, and relevant
environment-variable names. Secret values are never recorded.

Reproduction of the benchmark means identical decisions and primary reason
codes for identical bytes. Reproduction of scientific payloads uses a
bundle-specific tolerance frozen before registration.

## 16. Role of existing observations and language models

The 2026-07-13 audit and all multi-model reviews are exploratory. They motivate
cases but do not enter confirmatory denominators. Raw materially used model calls
retain exact requests/responses and observable serving metadata. A cloud label
does not establish immutable weights or backend reproducibility.

`protocol/MODEL_REVIEW_PROTOCOL.json` freezes a ten-slot, 49-source-file review
surface with distinct technical roles, concurrent one-attempt execution, a
closed response schema, and explicit prohibitions on retry, replacement, voting,
and claim authorization. The first locally retained attempt
`reviews/model_review_20260713T225218Z/` contains ten transport failures caused
by sandbox denial of loopback access, zero model responses, and zero findings.
Its raw prompts and source snapshots are excluded from source Git and from the
public review packet. Tests reconstruct the same closed transport-failure shape
in a temporary directory. This attempt is operational failure evidence, not
scientific evidence and not a completed multi-model review. A future successful
execution receives a new batch identity; local retention of this failed attempt
does not authorize any paper claim.

## 17. Claim discipline

- A digest is not a signature.
- Signature validity, identity authorization, subject binding, payload integrity,
  provenance policy, and scientific reproduction are separate reported checks.
- A local linked list is not a public blockchain.
- An authorized signature does not make false science true.
- “All attacks” means only all compatible cases in the frozen released catalog.
- Exploratory, confirmatory, reproduction, and post hoc findings remain visibly
  separated in the paper.

## 18. Items required before registration

- `TBD-BEFORE-REGISTRATION`: target venue and disclosure/checklist rules.
- `TBD-BEFORE-REGISTRATION`: final schema, JCS vectors, and reason taxonomy.
- `TBD-BEFORE-REGISTRATION`: release-specific public GitHub workflow/ref/source
  identity and trusted-root bytes. The action and verifier versions are selected
  and exactly pinned but remain subject to independent review/freeze.
- `TBD-BEFORE-REGISTRATION`: trust roots, transparency verification, and
  compromise/rotation procedure.
- `TBD-BEFORE-REGISTRATION`: frozen bases, licenses, generator, seeds,
  compatibility matrix, planned case count, and oracle.
- `TBD-BEFORE-REGISTRATION`: proposition/RQ/outcome/falsification/claim table and
  timeout/retry/deviation rules.
- `TBD-BEFORE-REGISTRATION`: clean build/reproduction commands and tolerances.
- `TBD-BEFORE-REGISTRATION`: independent oracle reviewer and reproducer.
- `TBD-BEFORE-REGISTRATION`: OSF/archival repository and version-specific DOI
  strategy.
