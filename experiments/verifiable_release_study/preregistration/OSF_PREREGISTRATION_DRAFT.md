# OSF Preregistration Draft

Status: **draft only; do not submit yet**  
Protocol version: `0.3.0-draft`

## Title

From Checksums to Attestations: Evaluating Tamper-Evident Scientific Releases
Under Software and Model Drift

## Study type and objective

This is a deterministic computational systems benchmark, not a random-sample
experiment. It evaluates four release-verification profiles on a complete frozen
set of clean and adversarial packages.

Two questions are registered separately:

1. whether each implementation conforms to its own exact profile contract;
2. which target-invalid packages each partial profile accepts relative to one
   frozen target scientific-release contract.

The study does not test whether cryptography establishes scientific truth.

## Prior observations

Before registration, the authors audited current A.M.Y/Atlas code and artifacts
and ran recorded model-assisted protocol critiques. These exploratory materials
motivated the profile ablations and attack candidates. They are disclosed under
`audit/` and `reviews/` and excluded from all confirmatory counts.

No confirmatory corpus has been generated or executed at the time of this draft.

## Verification profiles

- `P0-METADATA`: bounded top-level existence and JSON syntax only.
- `P1-CHECKSUM`: strict JCS/schema/path/role/closed-world inventory plus current
  payload size and SHA-256; no authenticated manifest identity.
- `P2-SIGNATURE_ONLY`: authenticated exact manifest subject, signer/workflow, and
  public transparency policy; no manifest/payload/provenance semantics.
- `P3-ATTESTED_RELEASE`: P1 + P2 + standard `actions/attest` SLSA provenance
  for workflow/builder/source dependency plus authenticated v0.2 manifest
  metadata for clean source, tree, source snapshot, dependency lock, and
  execution image. The latter values are workflow-authored, not independently
  certified by GitHub/Sigstore. The snapshot target is exact opaque-byte
  binding; tar-member equivalence to the declared Git tree is not claimed or
  scored.

The complete submitted registration will embed the frozen profile text and trust
policy, not rely only on a mutable repository link.
The current v2 production verifier additionally requires the policy's exact
SHA-256 from the external R0 identity, validates that policy against its exact
hash-bound closed schema, and binds the policy, policy-schema, and result-schema
digests into every structured terminal result. The historical v1 policy and P2
smoke remain unchanged and cannot be substituted for this future v2 freeze.

## Research questions and exploratory separation

Register RQ1–RQ5 from `protocol/PROTOCOL_DRAFT.md` after all draft/TBD markers
are resolved. RQ6 concerns the already inspected A.M.Y/Atlas baseline and is an
exploratory/descriptive case study; it is disclosed but excluded from the
confirmatory block. A future confirmatory RQ6 would require a genuinely held-out
snapshot selected before inspection.

## Design

- Within-case deterministic profile ablation.
- Unit: base release bundle × compatible mutation operator.
- Every compatible unit is evaluated by P0, P1, P2, and P3.
- Every case has two labels: one profile-independent target decision and one
  profile-specific expected decision/reason.
- Compatibility depends only on frozen structural prerequisites.
- Mutation generation, oracle, verifier, and result evaluation are separate
  modules.
- Verifiers see opaque case IDs; labels are joined only after results are
  complete and hashed.
- Synthetic pilot fixtures are excluded from confirmatory results.

## Corpus and sampling plan

There is no random sample and no power calculation. The confirmatory dataset is
the complete frozen compatibility matrix. Deterministic reruns do not increase
sample size.

`TBD-BEFORE-REGISTRATION`: enumerate every base bundle, origin/license, exact
base SHA-256, mutation prerequisite, compatibility row, seed, deterministic
generation order, and planned case count. Freeze and archive the generator,
catalog, bases, oracle, compatibility matrix, and environment before
registration.

The current draft R0 base registry defines six CC0, study-generated S1 bases
covering all six release kinds in the manifest schema. An exploratory clean-base
build and same-environment replay exist, but expected hashes remain intentionally
unset in the draft registry. A separate selected-profile clean-base run now
replays P0–P3 over all six bases (24 clean `ACCEPT/OK` results) under controlled
public test PKI, and its source fixture is a parseable deterministic USTAR. This
does not close the gate. A separate generic development generator now implements
all 41 branches, and a schema-closed 164-row draft oracle replays solely from
catalog expectations without reading results. Those same-author artifacts have
not generated the 6×41 corpus and are not independently reviewed or frozen; the
S2 A.M.Y production base, cross-platform selected-profile replay, prerequisite
resolution, and final frozen hashes are still required.

A current replay leaves the retained six-base run internally valid and preserves
all 24 clean decisions, while explicitly reporting three source files changed
after that run. The retained run is not relabeled as current-code evidence.

The immutable historical v0.3 compatibility product contains 204 rows. The
selected-profile v0.4 draft contains the complete 246 S1 candidate units: 185
currently compatible, 54 pending policy-freeze evidence, 6 structurally
incompatible public-keyless transparency rows assigned to S2, and one B04
inventory row without a unique required-role mutation target. The generator
uses clean-base validation only to establish fixture availability and does not
read mutation outcomes, target decisions, or profile expectations. The
separate same-worktree validator recomputes every prerequisite and verifies that
poisoning all target/expectation fields leaves the 246 rows unchanged. It also
recomputes 245 exact resolved mutation plans and the one exact unavailable plan.
A separate same-worktree development receipt exercises 65 target-dependent
plans only on disposable copies and fixes all confirmatory, production, review,
and manuscript boundaries to false. Pending rows must resolve before
registration; they cannot be dropped after execution.

The 18 path-safety units previously pending on filesystem support are now
compatible because hash-bound probes passed in both planned environments. This
is R0 compatibility evidence, not a confirmatory verifier outcome; any relevant
environment or probe-source change requires a rerun.

The derived confirmatory case archives do **not** exist before registration.
They are generated afterwards from the frozen R0 inputs. Their archive and
per-case SHA-256 values are recorded as R1 execution provenance, not claimed as
known at registration time. A mismatch between planned and generated case sets
is a retained generation failure and cannot be relabeled `NOT_APPLICABLE`.

## Outcomes

### Primary

- full observed case-by-profile decision matrix;
- all mismatches between observed and profile-expected decisions/reasons;
- target-invalid accepts by profile and attack family, with exact case IDs and
  numerators/denominators;
- clean-package failures by profile/environment;
- decision/primary-reason disagreement across environments.

The authoritative denominator for profile conformance is every row in the
frozen planned compatible `base × operator × profile × required-environment`
product. `ACCEPT`, `REJECT`, `ERROR`, `MISSING_EXECUTION`, and
`GENERATION_FAILURE` form a mutually exclusive partition whose counts must sum
to that planned denominator. Missing generation/execution is therefore not
removed through a terminal-only denominator; it is reported separately and
makes complete-conformance claims false. `NOT_APPLICABLE` can arise only from
the frozen pre-execution compatibility matrix and lies outside the compatible
product. Four profile rows from one base×operator unit are paired observations,
not independent units. Family totals are finite-corpus enumerations and no
single pooled value is promoted as a security score.

The preregistration will include a proposition table with one row per claim:
`proposition → applicable units → observed field → deterministic decision rule
→ falsification condition → permitted wording`. Until that table is frozen and
the dummy analysis passes, no result is designated for the abstract or
conclusion. Positive wording is allowed only when proposition support and
eligibility pass with no falsification; every falsified or incomplete
proposition must use its required negative wording and cannot be silently
omitted from the conclusion.

`protocol/PROPOSITION_MATRIX_DRAFT.json` now contains the complete draft table,
including missingness and abstract-eligibility rules. The submitted registration
will embed its independently reviewed frozen bytes; the present draft does not
authorize confirmatory execution.

There is no pooled “security score,” no macro headline, and no claim that a
finite-corpus proportion estimates real-world attack prevalence.

### Secondary

- secondary reason-code agreement and precedence;
- claim-evidence coverage;
- runtime/resources only if their measurement method is frozen before
  registration.

## Analysis plan

- Release all case-level data and the exact deterministic analysis command.
- Report each case/family before descriptive totals.
- Separate implementation-conformance failures from target-contract misses.
- Do not use p-values, confidence intervals, bootstrap, or repeated deterministic
  runs to imply a sampled population.
- Generate manuscript numbers, tables, and figures from released data only.
- Retain and report every negative, unexpected, and infrastructure result.

## Compatibility and exclusions

- A case is `NOT_APPLICABLE` only when a frozen prerequisite is structurally
  false for a base bundle.
- Applicability cannot depend on observed verifier output.
- No terminal result is excluded because it is inconvenient or unexpected.
- A crash is `ERROR`, remains in data, never satisfies target `REJECT`, and is a
  clean failure if the target is `ACCEPT`.
- No exclusion rule may be added after labels and decisions are joined.

## Independent oracle review

Before registration, a qualified human who did not implement the verifier,
mutation generator, or analysis and did not author the catalog, oracle
expectations, or propositions will review exact SHA-bound bytes. The required
record covers all 41 catalog cases, 164 case×profile oracle rows, twelve
propositions, 246 compatibility rows, and seven compatibility-policy decisions.
The reviewer will have neither confirmatory-outcome access nor subject-file
write access during review and will disclose qualifications, compensation, and
specified conflicts.

The reviewer must receive the expected JCS-manifest and USTAR-packet SHA-256
values through an authorized channel external to the packet, bind both in the
record, and detached-authenticate the exact completed record bytes under a
separate reviewer-identity policy. Mechanical hash/schema/archive validation
does not establish authorization, competence, independence, care, or scientific
truth. Model-assisted review does not satisfy this gate by itself.

The reviewer identity and OIDC issuer must be preauthorized before review in a
separately SHA-bound frozen policy, together with the authorization record,
trusted-root SHA-256, exact Cosign version/platform/binary SHA-256, and offline
verification flags. Regex identity/issuer matches and `--insecure-ignore-sct` /
`--insecure-ignore-tlog` are forbidden. Versions through Cosign 2.6.1 and 3.0.3
are rejected under GHSA-whqx-f9j3-ch6m; any selected version must be checked
again at freeze time rather than accepted as “latest.” The current policy is an
unusable null-valued template and permits neither freeze nor authentication.

`TBD-BEFORE-REGISTRATION`: identify and authorize the qualified reviewer,
archive the signed/dated exact-byte review record and detached evidence, and
resolve every required change against a newly identified packet.

## Stopping and retry rules

After registration, generate every planned case and execute every frozen
compatible case exactly once in each required environment. Continue until every
planned unit has a retained terminal result or a retained terminal generation/
infrastructure failure. Do not stop on an effect, favorable score, or manuscript
quality.

Before registration, freeze per-case and full-run timeouts, the maximum attempt
count, and the exact typed infrastructure predicates. `SCIENTIFIC_INTENT` is
durably persisted before every generator/verifier spawn; any post-intent state
is permanently non-retryable. Attempt two requires the SHA-256 of the already
persisted attempt-one classification and is authorized only by exactly one
pre-intent predicate with no outcome exposure. Invalid, overlapping, late, or
missing evidence fails closed. A rerun repeats the whole affected environment,
retains every prior attempt, and never overwrites output.

Official selection covers the author and pinned-Linux environments in one
campaign-wide seal before either result can be decoded. An environment with no
official attempt contributes `MISSING_EXECUTION` for every planned row;
unauthorized attempts remain public but cannot enter the observation ledger.
Changing verifier/generator code after a confirmatory attempt creates a new
exploratory version or a new preregistration; it cannot repair the registered
result in place.

`protocol/RUN_EXECUTION_POLICY_DRAFT.json` is the machine-readable draft for
these rules. It fixes one case attempt, at most two complete-environment
attempts, outcome-blind infrastructure classification before result/oracle
inspection, immutable retention, and exact timeout/deviation dispositions. It
binds 16 implementation/schema/test/lock inputs; the historical receipt reports
29 tests, the v2 receipts report 52, and the active v3 receipt reports 61. The
additional v3 cells exercise only a local contract-test intent chain and do not
establish authenticated checkpoints, rollback detection, recovery, or
classifier derivation. Those tests establish neither OS-level isolation nor
external authentication, qualified human review, RG-006 completion, or
confirmatory permission. Eleven controls and 54 compatibility rows remain open,
so the retained validation remains `NO-GO`; this text is not a frozen runner or
registration.

## Reproduction

Required environments:

- recorded author environment;
- fresh Linux CI from a pinned image digest;
- independent execution of the complete frozen benchmark by a qualified
  external person/service before manuscript submission. This is a mandatory
  study gate. Artifact availability alone does not satisfy it, and claim C011
  remains forbidden until a signed, dated external execution record binds
  hash-identical R0/R1 inputs and the complete result comparison.

Benchmark reproduction requires identical decisions and primary reason codes for
identical bytes/trust policy. Scientific-payload reproduction uses per-bundle
tolerances frozen before registration.

## Open materials and release identity

Before confirmatory generation/execution, archive and hash R0:

- registration export;
- protocol, threat model, profiles, trust policy, schemas, reason codes;
- exact v2 policy, policy schema, result schema, verifier/CLI bytes, and the
  externally recorded expected-policy SHA-256;
- catalog, compatibility matrix, and oracle;
- mutation, verifier, runner, and analysis source;
- exact opaque source-snapshot bytes, dependency lock, and execution image;
- pilot/confirmatory separation record;
- independent oracle review.

After registration, R1 adds generated case hashes, raw results, logs, and the
complete generation/execution attempt ledger. R2 adds only analyses and paper
artifacts derived from R1, while linking exact R0 and R1 identifiers.

The exact link contract is
`protocol/RELEASE_LINEAGE_CONTRACT_DRAFT.json`. A human version label is never
an execution identity. Each frozen stage requires the separately labeled Git
object IDs and SHA-256 values for source snapshot, lock, image, manifest,
attestation policy, trusted root, bundle, verifier, output schema, and transport
archive, plus a version DOI. The current contract is internally valid but
reports `NO-GO`; it is not itself a registration or an external snapshot.

The final versioned deposit includes raw case packages/results/logs, analysis,
figures, paper source/PDF, claim ledger, content manifest, in-toto/SLSA
attestation, public verification bundle, license, and data dictionary. Any
correction creates a new version-specific DOI and leaves prior bytes intact.

## Deviations

Every deviation is appended to a machine-readable ledger with date, registered
rule, actual action, reason, affected outputs, and confirmatory/exploratory
classification. The registration is never rewritten.

## Model assistance

Models may review drafts and code but do not set oracle labels, exclusions, or
citations. Material calls retain exact request/response bytes and observable
model/Ollama metadata. Hidden cloud weights and serving state are declared
unreproducible unless an immutable provider identity becomes independently
available.

## Pre-registration robustness engineering

`protocol/ROBUSTNESS_CATALOG_DRAFT.json` is a separate, non-confirmatory S0
engineering stratum. Its TOCTOU and fault-injection cases may be executed while
the verifier is still changing, but they are excluded from every primary
denominator and proposition. The retained author and pinned-Linux executions
passed all 12 scheduled tests. This does not establish exhaustive race freedom;
it establishes only the named interleavings and correct separation of
`REJECT/INPUT_CHANGED` from `ERROR/INTERNAL_ERROR`. The catalog, implementation,
and remaining filesystem assumption must be independently reviewed and frozen
before registration.

## Registration readiness

- [ ] All `TBD-BEFORE-REGISTRATION` markers resolved.
- [ ] Synthetic pilot complete and isolated.
- [ ] S0 robustness catalog implemented, independently reviewed, and frozen;
      retained engineering outcomes excluded from confirmatory denominators.
- [ ] Confirmatory derived cases not generated or executed; frozen bases,
      generator, seeds, catalog, oracle, and compatibility matrix archived.
- [ ] Four profile contracts and schemas frozen.
- [ ] Public workflow/trust/transparency policy frozen and executable; exact
      v2 policy SHA-256 independently recorded in R0 and accepted by the CLI.
- [ ] Every catalog/oracle row independently reviewed.
- [ ] Compatibility matrix fixed using structural prerequisites only.
- [x] Dummy analysis tested on a retained 1,480-row synthetic ledger without
      confirmatory data; it authorizes no manuscript claim and must be rerun
      against the final independently reviewed frozen design.
- [ ] Clean build/reproduction command and tolerances fixed.
- [ ] OSF export checked for secrets/personal data.
- [ ] Registration submitted and immutable identifier recorded before any
      confirmatory generation/execution.
