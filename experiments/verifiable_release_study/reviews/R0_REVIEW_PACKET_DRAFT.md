# R0 RG-004 Human-Review Packet Draft

Status: **preparation only; unreviewed; not frozen**  
Registration gate: **RG-004 remains open**

Building this packet does not perform, simulate, or imply independent human
review. No reviewer has approved these bytes, and this draft is not evidence
that registration, production release, external reproduction, or scientific
validation occurred.

## Packet contract

`scripts/build_r0_review_packet.py` reads one explicit, UTF-8-bytewise sorted
list of regular source/contract files plus exact synthetic base-aware and RG-006
`NO-GO` test receipts. It preserves historical receipts while identifying the
current timestamped base-aware receipt and its separate same-worktree
validation. The list
covers the current protocol,
41-case selected attack catalog, 164-row oracle, twelve propositions, 246-row
compatibility matrix, six-base registry, policies, schemas, implementations,
the draft manuscript skeleton plus its stage linter/tests, the
authoritative-input analysis and 17 focused tests, the exact-locator claim
ledger and fail-closed validator, the byte-preserved historical v1 and separate
non-injectable production v2 attestation cores, the SHA-bound pre-R0 closure
ledger, the frozen exploratory ten-slot model-review design, its first
mechanically validated all-transport-failure summary, and focused tests. The
summary commits to the separately retained exact requests, errors, and source
inventories; no model response or finding exists in that batch. The closure ledger
retains all ten blocking gates, seventeen unmet evidence requirements, and
explicit prohibited inferences; its structural validity is not approval. The
packet builder does not glob or walk directories and rejects missing
paths, duplicate logical paths, symlinks (including symlinked ancestors), and
nonregular files.

All empirical and confirmatory run-output roots remain forbidden subjects. The
only output exceptions are the exact allowlisted historical and active
base-aware receipts and validations plus the byte-preserved historical
`development_checks/RG006_RUNNER_CONTRACT_TEST_2026-07-13.json`, the historical
v2 candidate `development_checks/RG006_RUNNER_CONTRACT_TEST_V2_2026-07-14.json`,
the historical v2 receipt
`development_checks/RG006_RUNNER_CONTRACT_TEST_V2_2026-07-15.json`, two
preserved v3 candidates, and active timestamped
`development_checks/RG006_RUNNER_CONTRACT_TEST_V3_2026-07-15T034921Z.json`.
Their schemas or validators fix the receipts to `NO-GO` and every
confirmatory/review boundary to false. The active v3 receipt also keeps every
production control open and limits both its local scientific-intent evidence
and storage-fault evidence to `PARTIAL`. It does not claim same-UID exclusion,
rollback or suffix-deletion detection, an authenticated external checkpoint,
post-crash recovery, classifier derivation, power-loss durability,
cross-filesystem equivalence, production-adapter integration, or runner-wide
persistence coverage.
The builder reads no pilot, selected-base-run, robustness-run, R1/R2,
confirmatory-case, or confirmatory-result path. It does not import or execute a
verifier, generator, evaluator, oracle, or model-review implementation.

An earlier packet candidate remains only a historical preparation snapshot.
Any change to a subject byte—including these pre-R0 corrections—requires a new
manifest hash, packet hash, destination, and external authorization path; the
old candidate cannot be relabeled as current.

The builder creates exactly these two files in a new output directory:

- `R0_REVIEW_SUBJECT_MANIFEST.jcs.json`: RFC 8785 canonical JSON. Each selected
  artifact has its relative path, role, raw-byte SHA-256, and byte length.
- `R0_REVIEW_PACKET.tar`: uncompressed USTAR containing the canonical manifest
  and every listed artifact. Members are UTF-8-bytewise path sorted; each is a
  regular file with mode `0644`, `mtime=0`, `uid=0`, `gid=0`, and empty owner
  names.

The archive cannot contain its own SHA-256 without a circular identity. The
builder therefore prints the raw manifest and packet SHA-256 values to stdout;
those values must be recorded and authorized outside the packet.

## Deterministic build

From the study root, with an existing parent directory and a destination that
does not yet exist:

```bash
uv run --frozen python scripts/build_r0_review_packet.py \
  --output <new-output-directory>
```

Rebuilding unchanged subjects at a different destination must produce
byte-identical manifest and USTAR files. A changed subject byte, path, role, or
packet contract produces a different manifest and packet identity.

The receiver can mechanically verify a packet only after obtaining both
expected hashes through an authorized channel external to that packet:

```bash
uv run --frozen python scripts/verify_r0_review_packet.py \
  --packet-directory <packet-directory> \
  --expected-manifest-sha256 <64-lowercase-hex> \
  --expected-packet-sha256 <64-lowercase-hex> \
  [--review-record <completed-record.json>]
```

This command checks raw hashes, strict duplicate-free JSON, RFC 8785 bytes,
closed manifest shape, USTAR ordering/metadata/member bytes, the review-record
schema, and submitted-record subject binding. Its output deliberately fixes
detached authentication, reviewer authorization, reviewer competence, and
`rg004_complete` to `false`.

## Reviewer identity preauthorization

The signer cannot be selected from the identity found in a completed bundle.
Before review begins, the gate authority must replace
`protocol/R0_REVIEWER_IDENTITY_POLICY_TEMPLATE.json` with a newly identified,
schema-valid frozen policy and distribute its expected SHA-256 externally. The
frozen policy requires one exact certificate identity, one exact OIDC issuer,
an independently retained authorization record, a pinned trusted root, and an
exact Cosign version/platform/binary SHA-256. Regex identity/issuer flags and
the SCT/Tlog bypass flags are forbidden.

The security floor rejects Cosign versions through 2.6.1 and 3.0.3 because
GHSA-whqx-f9j3-ch6m documents an affected Rekor-binding verification path;
2.6.2 and 3.0.4 are the first patched versions in those major lines. This floor
is not a permanent endorsement: the selected exact release must be reviewed
again for newer advisories at freeze time. The retained template has null
identity/tool/root values and its static validator reports `NO-GO`.

## Future reviewer workflow

The future reviewer must receive the expected manifest SHA-256 and packet
SHA-256 through an externally authorized channel, not learn them only from the
packet under review. Before reviewing content, the reviewer or gate authority
must recompute both raw-byte hashes, compare them to those external values, and
verify that every archive member exactly matches the canonical subject
manifest.

The reviewer then copies
`protocol/R0_HUMAN_REVIEW_RECORD_TEMPLATE.json` to a new record and completes it
under `schemas/r0-human-review-record.schema.json`. The shipped template
enumerates all current coverage but is deliberately valid only with
`record_status: template_unreviewed`, null identity/bindings/declarations, all
41 catalog-case decisions marked `NOT_REVIEWED`, 164 oracle decisions marked
`NOT_REVIEWED`, twelve proposition decisions marked `NOT_REVIEWED`, all 246
compatibility-row decisions marked `NOT_REVIEWED`, and seven
compatibility-policy decisions plus one manuscript-consistency decision marked
`NOT_REVIEWED`.

A `submitted` record is fail-closed. It requires:

- the exact externally supplied raw SHA-256 of both the subject manifest and
  packet;
- a stable reviewer identity, affiliation, qualification statement, relevant
  experience, and optional qualification-evidence URIs;
- an RFC 3339 `reviewed_at` value with an explicit UTC or numeric offset;
- explicit declarations that the reviewer did not implement the verifier,
  mutation generator, or analysis; did not author the catalog cases, oracle
  expectations, propositions, or manuscript skeleton; and is not a project
  author/investigator;
- explicit declarations of no confirmatory-outcome access, no prior development
  case-outcome access, and no subject-write access during review;
- explicit employment/supervisory, shared-funding, financial/consulting, and
  personal/competing-interest fields, compensation disclosure, aggregate and
  disqualifying-conflict declarations, and an independence statement;
- one decision for every one of the 41 catalog cases, 164 oracle rows, twelve
  propositions, 246 compatibility rows, and seven compatibility-policy
  questions, plus one explicit decision that the manuscript skeleton is
  consistent with the reviewed protocol, threat model, claim boundaries, and
  source ledger;
- findings and an overall `APPROVE`, `REQUIRES_CHANGES`, or `REJECT` decision.

Every `DISAGREE` or `REQUIRES_CHANGE` decision requires a rationale. Every
finding classified `REQUIRED_CHANGE` requires both a rationale and a concrete
required change. `APPROVE` is schema-valid only when every coverage decision is
`AGREE` and no required-change finding exists. A non-approval requires at least
one required-change finding.

Schema validation enforces record shape and coverage, but all declarations are
self-assertions until externally assessed. It cannot obtain the authorized
external hash values or decide who is an authorized or qualified reviewer. A
consumer must compare both record bindings to externally authorized expected
hashes and evaluate reviewer authorization under a separately maintained
identity policy.

## Detached authentication and claim boundary

The completed record itself is the exact raw byte sequence to authenticate.
It has no self-hash and no field for an embedded signature or bundle. Do not
pretty-print, canonicalize, normalize line endings, or otherwise rewrite the
record after authentication.

Before RG-004 can close, the exact submitted record bytes require a detached
Sigstore bundle/signature, and that detached evidence must verify under a
separately authorized reviewer-identity policy. The detached evidence and
identity policy are external artifacts; neither is inserted into the record.

A valid detached signature establishes only that the authenticated record bytes
were associated with the verified identity under that exact policy. It does
not establish that the reviewer is competent, actually performed a careful
review, is free of undisclosed conflicts, or reached a scientifically true
conclusion. Qualification, independence, conflicts, technical adequacy, and
scientific truth remain separate judgments and evidence obligations.

Even a fully populated, schema-valid, hash-matching, correctly authenticated
record does not update `protocol/REGISTRATION_GATES.json` automatically. The
gate authority must separately determine that the reviewer is authorized and
qualified, that all required changes are resolved in newly identified subject
bytes, and that every other registration condition remains satisfied. Until
then, the only accurate statement is that an unreviewed packet was prepared for
a possible future RG-004 review.
