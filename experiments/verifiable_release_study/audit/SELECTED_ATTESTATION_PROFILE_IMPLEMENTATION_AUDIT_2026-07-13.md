# Selected production-attestation profile implementation audit

Prepared: 2026-07-13  
Classification: pre-registration static/code-contract audit  
Decision: **NO-GO; selected for implementation, not frozen**

## Scope and method

This audit examines the selected
`standard_provenance_plus_authenticated_manifest_metadata` profile, its two
historical v1 contracts, current v2 policy/result schemas, production manifest
schema, adapters, CLI, reason-code registries,
selected-profile S1 migration records, tests, and retained production-smoke
result. It also covers the separated 41-case mutation generator, 164-row draft
oracle, result evaluator, and current clean-base replay. The deterministic
scanner parses Python ASTs and JSON contracts,
inspects the controlled USTAR structure, and inventories retained records. It does
not invoke GitHub CLI, contact Sigstore/GitHub, run a workflow, verify a new
signature, or read confirmatory results.

Normative machine records:

- raw audit: `audit/SELECTED_ATTESTATION_PROFILE_AUDIT_RAW_2026-07-13.json`,
  pretty-file SHA-256
  `2bd43c22f3b00b26a13a68d63f38e93d129b8ce2c2371ca5930fe6a58ff6de8c`;
- canonical raw SHA-256
  `49f13a47ea8a98000d8827aa2256441e36f674344178bd90b10def7e6aa23cd3`;
- replay validation:
  `audit/SELECTED_ATTESTATION_PROFILE_AUDIT_VALIDATION_2026-07-13.json`,
  SHA-256
  `e2ddd5b961ad1381d26a45d6dbf67e13a354aa20baafc0486a921b79c933a20d`;
- scanner SHA-256
  `717d3ceae1a49d0dcd08750c765bad0224fd42307611a5c3ab21e072f45e322d`.

The validator rebuilt the audit from current inputs and obtained the same
canonical bytes with zero errors. This is a same-environment replay, not an
independent reproduction.

## Findings

### AP-01 — Selection timing and status

The decision record selects the recommended profile and declares that no
confirmatory outcomes were observed before selection. Its status remains
`selected_for_implementation_not_frozen`. This is an authored chronology
record, not an independently time-stamped registration.

### AP-02 — Implemented contract controls

The scanner found all 27 listed static controls present in the exact audited
bytes. In bounded terms, the implementation:

- preserves default `actions/attest` SLSA provenance and does not add custom
  SLSA materials;
- requires one exact manifest subject and a schema-closed v0.2 manifest;
- labels clean/tree/snapshot/lock/image values as workflow-authored rather than
  independently certified;
- cross-binds snapshot and lock digests to manifest payload entries;
- refuses P3 through the attestation-only API;
- routes P3 through authenticated verification plus all six P1 checks and
  before/after manifest identity checks;
- exposes the production manifest-schema digest and P1 states in accepted P3
  evidence;
- uses only reason codes in the historical registry plus its versioned
  production extension;
- validates every structured CLI decision against a separately hash-bound
  production result schema;
- requires an externally expected policy SHA-256 before policy use, validates
  a closed v2 policy schema, and revalidates immutable policy, policy-schema,
  and result-schema bytes at each library call;
- carries all three contract digests in every structured terminal result and
  validates library `ACCEPT` serialization against the exact result schema;
- preserves the five identified historical v1 artifacts byte-for-byte.

These are present-byte code/contract observations. They are not evidence that a
real A.M.Y bundle passes the profile.

### AP-03 — Output-contract hardening

The v1 policy, result schema, CLI, cryptographic core, and retained genuine-P2
result remain byte-identical. Their policy/result-schema SHA-256 values are,
respectively,
`68ea605c25a8e73ebe955a1bfd3977a309f13b40b9a112aee6b2e9bc5cd38c26`
and
`64eef1a87da45dff355047963ebe762dfced1a2ba7e60be9a87dfcc28a1e2c18`.
They are historical evidence and were not edited or reinterpreted as v2.

The current v2 line has these exact identities:

- policy template:
  `0d24ac7288782b3d8ca681bc6a986ad421e13be5480b10bffe3ad0b2433b45cf`;
- closed policy schema:
  `d7bbbfa9045dceb6c63244d627396c380bf76a7a7cdaa5883fad6411ff19510a`;
- terminal-result schema:
  `fca95c09b26590c8ca84346c72627b07bf4de967cc4135d585eab6f825ebdaa4`.

The loader requires the policy SHA-256 from an external R0/deposit channel
before policy use. The authorized policy binds both exact schema digests. The
library stores immutable raw bytes for all three documents and rehashes,
reparses, and revalidates them whenever a verification wrapper is called; it
rejects a plain mutable policy dictionary. Its evidence snapshot is immutable,
and `evidence_to_json_v2` validates the `ACCEPT` against the exact retained
result-schema bytes. The CLI independently validates every terminal object and
emits no structured stdout if it cannot establish the complete contract first.

Every v2 `ACCEPT`, `REJECT`, or `ERROR` requires the policy, policy-schema, and
result-schema SHA-256 values. A P3 acceptance additionally requires the
production manifest-schema hash and all six P1 checks as `PASS`; P2 is forbidden
from carrying those integrated-P3 fields. Rejections remain limited to the
versioned reason vocabulary. Twenty-one v2 adversarial/regression tests cover
policy/result-schema substitution, duplicate policy/schema keys, unknown
fields, template misuse, frozen cross-field mismatch, mutable-dictionary and
post-load mutation attempts, immutable evidence snapshotting, library output
validation, CLI suppression, and the exact historical v1 invariants.

The integrated manifest-assertion parser now preserves the specific
`JSON_INVALID` and `DUPLICATE_JSON_KEY` reasons for authenticated malformed
manifest bytes instead of collapsing both into `PROVENANCE_INVALID`. The closed
result vocabulary already contains these codes; this changes diagnostic
specificity, not acceptance policy.

Historical v1 direct execution initially exposed an import-path defect. The entry
point was corrected and a subprocess regression test now requires direct
execution to emit a schema-valid `INPUT_MISSING` rejection. This development
failure was not recoded as a successful verifier observation.

### AP-04 — Synthetic-test boundary

The integrated P3 unit test exercises a clean payload and a changed lockfile,
but deliberately mocks `_verify_github_manifest_attestation`. It therefore
tests P1 integration and result propagation, not real Sigstore cryptography.
The retained production-smoke inventory contains one genuine P2 GitHub CLI
result and zero P3 records for the selected A.M.Y repository.

### AP-05 — Source-snapshot boundary

The production manifest schema identifies `source.tar` as
`application/x-tar` with assurance
`exact-opaque-bytes-no-git-tree-equivalence-claim`. P1/P3 recompute and bind the
exact tar bytes. The audited call scope does not inspect tar members or
reconstruct the separately asserted Git tree, and the profile now explicitly
forbids claiming that it does. This is a deliberate scope reduction, not a
missing success result.

The controlled S1 fixture now uses a syntactically valid deterministic USTAR:
10,240 bytes, SHA-256
`2bc8dc879609cf564b390de1036df57ea3e2dc6f6d16d7529a916d93eb58e8dd`,
with one canonical `SNAPSHOT.txt` member. This removes a prior media-type
mislabeling but does not expand production P3 into tar-member or Git-tree
semantic verification.

### AP-06 — Selected S1 migration state

The selected migration is now separately retained and replayed:

- six blueprint-preserving clean bases produced 24 schema-valid `ACCEPT/OK`
  profile results under controlled public test PKI;
- all 34 historical case IDs remain, seven selected semantic operators were
  added, and eleven changed provenance/manifest operators have explicit
  authenticated mutation contracts;
- the generic development generator implements all 41 selected operators; its
  isolation tests require the exact changed path set for each operator and one
  catalogued authenticated JSON Pointer for each of the eleven semantic cases;
- a schema-closed 164-row draft oracle is rendered only from catalog
  expectations, imports no generator/verifier/evaluator, reads no result, and is
  explicitly marked same-author, unreviewed, and unfrozen;
- disposable development fixtures produced 164 schema-valid case×profile
  results matching that draft oracle, and all 41 mutated trees replayed
  identically in the same environment;
- the complete 6 × 41 structural product contains 185 `COMPATIBLE`, 54
  `PENDING`, and 7 `NOT_COMPATIBLE` units; six are S2 transparency cases and
  one is the B04 inventory mutation whose required-role target is not unique;
- deterministic base-aware planning resolves 245 of 246 plans, and a separate
  same-worktree `NO-GO` receipt exercises 65 target-dependent plans only on
  disposable copies without invoking a verifier or joining the oracle;
- a counterfactual validation that poisons target decisions and profile
  expectations leaves all 246 compatibility rows unchanged;
- no adversarial confirmatory case was generated, executed, or read.

The 164 development evaluations are retained as command/output and source-hash
metadata in
`development_checks/SELECTED_PROFILE_FULL_GENERATOR_ORACLE_2026-07-13.json`
(SHA-256
`740aed6c4179861b3cb3eb26f883ff9e0a94a06a4a0c5fe02a32248d2a0cd719`).
Its separate structural/hash validation record has SHA-256
`3ab9b9336dc59a90bfdfbdb13eec5634681120a5becfee5f6042a838eeab4cf5`.
The v2-draft receipt requires equal RFC 8785 commitments to the 29-file source
inventory before and after execution. The base-aware receipt and its validation
have SHA-256 values
`1e7f75d4a3c0e25be91f649bd0a5b6e1798a9dff9b7eb56a717e72771b1830ba`
and
`4e3985d76485ee71bd217d26a86c754021551a397c051e67e799901b97b64c21`.
All four records explicitly classify the work as same-author development and
set every production, confirmatory, manuscript, and independent-review
indicator to false.

The current replay of the retained clean-base run remains internally valid and
preserves all 24 clean decisions, while reporting that three source paths now
differ from the run's archived source. This expected post-run drift is retained
as a warning, not misclassified as archive corruption or hidden by overwriting
the historical run.

The six-base post-registration case runner and independent oracle/proposition
review remain incomplete. The 164 development matches therefore establish
implementation consistency with a same-author draft oracle, not correctness of
that oracle, a frozen corpus, production Sigstore conformance, or confirmatory
results.

### AP-07 — Remaining blockers

The audit retains five profile-freeze blockers:

1. fourteen release-policy string locations still contain
   `TBD-BEFORE-REGISTRATION`;
2. `.github/workflows/attest-verifiable-study.yml` does not exist;
3. no real selected-repository P3 result is retained;
4. independent human review is incomplete;
5. the generic 41-case generator, 245 resolved base-aware plans, and 164-row
   draft oracle exist, but the frozen six-base post-registration case runner and
   its independent review do not.

Consequently RG-009 remains `partial`, RG-010 remains `open`, and
`freeze_permitted_now` is false.

## Assurance table

| Statement | Current support | Allowed now |
|---|---|---|
| Exact selected-profile schema/policy/code bytes are identified | Hashes plus deterministic static replay | Yes, snapshot-bound |
| Historical v1 policy/schema/CLI/core/P2-result bytes remain unchanged | Five exact SHA-256 invariants in validator and tests | Yes, historical-byte statement |
| V2 rejects a locally substituted policy without the external expected SHA-256 | Immutable-byte loader plus adversarial tests | Yes, implementation/test statement only |
| V2 library and CLI bind and schema-validate their complete output contract | Exact policy/schema bytes, AST audit, and 21 v2 tests | Yes, for tested implementation paths |
| P3 cannot be reported through the attestation-only API | Code inspection and unit test | Yes, implementation statement |
| Integrated P3 invokes all six P1 checks | Code inspection and synthetic mocked test | Yes, with synthetic boundary adjacent |
| Current template is a release-specific frozen and externally authorized policy | Fourteen unresolved strings; no R0 authorization | **No** |
| Controlled selected S1 snapshot is a valid deterministic USTAR | Exact fixture bytes plus tar parse and replay | Yes, fixture-only |
| Selected clean-base migration has six bases and 24 clean ACCEPT/OK rows | Separate same-worktree archive/payload/schema/verifier replay | Yes, exploratory controlled PKI only |
| Retained clean-base source still equals current source | Current replay reports three changed source paths while archive self-integrity and 24 decisions remain valid | **No** |
| Selected compatibility product has 246 outcome-blind structural rows | Deterministic rebuild, prerequisite recomputation, and counterfactual outcome poisoning | Yes, R0 planning only |
| Base-aware planning resolves every valid target without substituting a generic path | 245 exact plan commitments, one explicit unavailable plan, 65 disposable executions, collision test, and forged-plan rejection | Yes, development planning only |
| Generic selected mutation generator covers all 41 IDs | Branch coverage, exact tree deltas, semantic JSON-pointer isolation, and same-environment replay | Yes, development fixture only |
| Draft oracle contains all 164 case×profile expectations without observed fields | Closed schema plus deterministic catalog-only replay | Yes, as a same-author draft only |
| Oracle and six-base case runner are independently reviewed and frozen | No signed non-implementer review; 54 compatibility rows remain pending | **No** |
| A real A.M.Y release passed P3 | No retained record | **No** |
| Source tar reconstructs the declared Git tree | Outside selected profile | **No** |
| GitHub/Sigstore certified clean/tree/lock/image truth | Values are workflow-authored | **No** |
| Profile is preregistered, frozen, or production-ready | Five blockers remain | **No** |

## Development checks performed

At this working snapshot, `uv run --frozen --extra pilot pytest -q` completed
with exit code zero and reported `208 passed in 47.49s`. The suite covered the
attestation-profile decision, historical v1 and current v2 adapters/result
schemas, policy-schema and substitution defenses, protocol validation, selected
audit, base replay, catalog, compatibility matrix, fixture, generator/oracle,
base-aware planning, development-receipt tamper rejection, RG-006, review-packet,
and release-lineage contracts. This aggregate console observation is not a
detached-authenticated external receipt; the focused retained receipts remain
the machine-bound evidence. All are same-worktree development checks, not
confirmatory denominators, independent review, or a substitute for the absent
real A.M.Y P3 run.

## Permitted one-sentence summary

> At the identified pre-registration snapshot, the selected adapter was
> statically consistent with default GitHub provenance plus explicitly
> workflow-authored manifest metadata; its v2 contract layer required external
> policy identity and exact schema binding, and its synthetic integrated path
> invoked all P1 checks, but no real A.M.Y P3 execution or profile freeze had
> occurred.
