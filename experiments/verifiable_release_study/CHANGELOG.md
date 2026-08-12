# Study Design Changelog

## Unreleased design hardening — 2026-07-13

- Added a production GitHub/Sigstore adapter that invokes an exactly hashed
  GitHub CLI binary without a shell, snapshots verification inputs, applies
  bounded parsing, and requires exactly one authenticated verification result.
- Retained an offline, pinned-Linux P2 interoperability smoke against a genuine
  public GitHub CLI v2.96.0 Sigstore/Rekor bundle; explicitly excluded it from
  A.M.Y, P3, confirmatory, and independent-reproduction claims.
- Added release-specific identity, trusted-root, source, workflow, material, and
  provenance policy fields plus immutable action/tool pins.
- Added a machine-readable 14-gate registration registry. The protocol validator
  now reports and enforces its computed GO/NO-GO state, validates cited evidence
  paths and immutable pins, and hashes the expanded normative contract set.
- Recorded the current honest state as NO-GO: after making external
  reproduction mandatory, 10 blocking gates remain incomplete and 47 explicit
  registration TBD markers remain.
- Rebuilt the dummy-analysis join as a fail-closed replay of the authoritative
  catalog, compatibility matrix, and oracle. It now rejects copied-label drift,
  duplicate composite cells, an incomplete Cartesian product, and cross-profile
  generation/archive mismatches; PR-001 is S1-only, PR-003/PR-006 are honestly
  non-evaluable under observation-ledger v1, PR-008 has exact profile×family
  breakdowns, and synthetic data can never authorize manuscript claims. The
  focused analysis suite now has 17 tests.
- Replaced path-only claim citations with canonical exact-path, locator, and
  raw-SHA-256 references. A fail-closed validator mechanically resolves 70
  references for 40 bounded claims, leaves seven unauthorized claims empty,
  and derives C043 directly as 185 compatible, 54 pending, and 7 structurally
  non-compatible rows without authorizing scientific conclusions.
- Added a pre-R1 manuscript skeleton whose abstract, results, discussion, and
  conclusion are mechanically locked. Corrected premature frozen/registered/
  reviewed language, aligned the A0–A13 threat table and R0→R1→R2 correction
  semantics, and completed related work from primary/official sources. Its
  linter now rejects inline-code/comment gate escapes, duplicate placeholders,
  forbidden claim shortcuts, unresolved citation slots, and unknown or missing
  source-ledger references. The R0 review record now requires an independent
  manuscript-consistency decision and a declaration that the reviewer did not
  author the skeleton.
- Split production attestation v2 from the byte-preserved historical v1 core.
  V2 now binds immutable numeric repository and owner IDs, has no injectable
  subprocess runner in its public API, rejects v1 evidence objects, and refuses
  to treat action/dependency pins as authenticated workflow-byte evidence. Its
  31 focused tests pass, but the policy remains deliberately `NO-GO`.
- Added a SHA-bound pre-R0 closure ledger that maps those 10 blocking gates to
  17 still-open evidence requirements, retained current-evidence paths,
  prohibited inferences, external-actor dependencies, and exact acceptance
  tests. Its strict validator and five adversarial tests report structural
  validity while preserving `NO-GO`, zero confirmatory reads, and zero
  scientific-claim authorization.
- Froze a ten-slot exploratory Ollama Cloud review protocol over 49 exact source
  files, with distinct roles, closed response JSON, concurrent one-attempt
  execution, no retry, no replacement, no voting, and explicit provider-opacity
  boundaries. Added a no-network validation mode, strict batch validator, and 13
  adversarial tests.
- Retained the first complete ten-slot attempt rather than hiding or replacing
  it: this sandbox denied every loopback request with `Operation not permitted`.
  The canonical batch therefore records ten errors, zero HTTP responses, zero
  admissible reviews, and zero findings. RG-014 advances only from open to
  partial; successful execution and evidence-bound synthesis remain open.
- Added an explicit RG-004 review surface and a fail-closed unreviewed record:
  41 catalog-case decisions, 164 oracle-row decisions, 12 proposition
  decisions, 246 compatibility-row decisions, and 7 policy decisions. A
  schema-valid approval additionally requires non-authorship/non-implementation,
  outcome-blindness, no subject-write access, qualifications, conflict and
  compensation disclosures, and externally supplied packet identities.
- Added deterministic JCS/USTAR review-packet construction and mechanical
  verification against externally supplied manifest and packet SHA-256 values.
  The verifier fixes detached authentication, reviewer authorization,
  competence, scientific truth, and RG-004 completion to false; no human review
  is claimed and RG-004 remains open.
- Added a separate reviewer-identity preauthorization policy so signer
  selection cannot be learned from a completed record or signature bundle. Its
  current identity, issuer, authorization record, trusted root, Cosign version,
  platform, and binary digest are null, so authentication is forbidden. Exact
  identities are required; regex identity/issuer matching and SCT/Tlog bypasses
  are forbidden.
- Replaced the overbroad phrase "immutable deposit" with an exactly identified
  deposit plus append-only correction records, and made A.M.Y, Atlas, and AXIOM
  component-version reporting explicit for every applicable run.
- Added the 2026 Cosign Rekor-binding advisory to the source ledger and reject
  versions through 2.6.1 and 3.0.3. A future frozen policy must use an exactly
  hashed supported-major binary at or above 2.6.2/3.0.4 and record that the
  selected version was reviewed against the advisory; “latest” is never an
  execution identity.
- Made protocol, selected-catalog, and oracle validation reject duplicate JSON
  object names and non-standard numeric constants. The main validator now binds
  the exact catalog/oracle validator SHA-256 values, preventing stale validation
  records from surviving validator changes.
- Added a closed, hash-bound run-execution policy with exact acquisition,
  generation, P0-P3, Sigstore-inner, and whole-environment timeouts; one attempt
  per case; at most one outcome-blind complete-environment rerun; four explicit
  infrastructure predicates; eight non-retryable scientific conditions; and
  eight immutable deviation rules. Its retained validator reports internally
  valid NO-GO and reads no confirmatory result.
- Made qualified external execution of the complete hash-identical benchmark
  mandatory before manuscript submission. Claim C011 remains prohibited until
  a signed, dated external record exists; artifact availability and same-author
  replay do not satisfy the gate.
- Preserved RG-005 as open after an adversarial consistency pass found a real
  terminal-only denominator contradiction, absent dummy analysis, absent global
  conclusion logic, and wrong-primary-reason gaps. Those defects are now
  explicit work items rather than silently treated as a complete draft.
- Corrected those RG-005 defects and advanced the gate to partial: the planned
  product now uses a five-category exhaustive partition; every proposition has
  explicit abstract/conclusion handling; wrong primary reasons falsify affected
  claims; and a retained 1,480-row synthetic ledger exercises generation
  failure, missing execution, ERROR, wrong reason, cross-environment decision
  disagreement, and input-hash drift. Seven analysis tests pass, but final
  denominators, independent review, and freeze remain open.
- Added a deterministic read-only ATLAS code/artifact scanner, retained its raw
  machine-readable result, and confirmed byte-identical canonical replay in the
  same environment without importing ATLAS or deserializing model pickles.
- Expanded the evidence ledger with bounded observations for signature/artifact
  divergence, self-invalidating publication hashes, and absent active-root CI
  enforcement; no signer-authorization or malicious-tampering claim was added.
- Added a machine-validated twelve-row proposition matrix that maps every RQ and
  design requirement to its units, observed fields, denominator, deterministic
  support/falsification rule, missingness handling, permitted wording, and
  forbidden extrapolations. It remains partial until independent review/freeze.
- Added six deterministic CC0 R0 clean-base blueprints spanning all manifest
  release kinds, with binary/chunk-boundary, PDF, deep-path, empty-file,
  evidence-ledger, software, and opaque-model-exchange structures.
- Retained the first schema-invalid base-pilot result attempt instead of
  overwriting it; corrected case IDs and nested archive binding, then required
  result-schema validation inside the constructor.
- Retained a second six-base run that passes a separate archive/tree/manifest/
  payload/result validator and reproduces all base hashes in a same-environment
  rebuild. No adversarial confirmatory case was generated.
- Replaced the ambiguous “Sigstore bundle fixture” prerequisite name with
  “authenticated outer bundle fixture” so S1 controlled media is not described
  as production Sigstore conformance.
- Added a registry for all 28 structural prerequisites and a complete 204-row
  S1 base×operator compatibility matrix. Its generator is outcome-blind; the
  separate validator confirms 174 compatible, 24 pending, and 6 structurally
  non-compatible rows without consulting profile expectations or results.
- Retained hash-bound filesystem capability probes from the author macOS/arm64
  environment and the pinned offline Linux/amd64 image. Both passed symlink plus
  `O_NOFOLLOW`, hard-link, FIFO, regular-file, and directory-relative-open
  checks, resolving 18 path-safety compatibility rows without executing cases.
- Audited the exact pinned `actions/attest` implementation and retained the
  source hashes. Its default predicate lacks the custom clean-state and material
  fields required by the then-current P3 adapter. Preserved that mismatch as a
  historical audit and added four explicit replacement profiles before any
  confirmatory outcomes were observed.
- Reworked payload traversal around directory descriptors and `O_NOFOLLOW`,
  added a final identity rescan after hashing, and mapped observed path swaps to
  `INPUT_CHANGED`. Added a separate robustness catalog and scheduled TOCTOU/
  fault-injection tests without adding them to confirmatory denominators.
- Retained all 12 robustness tests in the author environment and in the exact
  pinned Linux/amd64 image with the repository and environment mounted read-only,
  no network, no capabilities, and no new privileges; added a hash validator and
  disclosed that the Linux venv was provisioned online from the lock beforehand.
- Added a deterministic deep audit of the newest legacy A.M.Y, ATLAS, AXIOM,
  DNA, and bond-energy manuscripts, their cited output bytes, producer links,
  missing publication artifacts, and current primary-reference metadata.
- Visually audited the exact latest DNA PDF and recorded that it omits data-
  availability/provenance material present in Markdown while printing a leaked
  reasoning tag and literal Markdown syntax; bound every visual observation to
  the reviewed PDF SHA-256.
- Added six bounded manuscript-audit observations to the claim ledger and kept
  every legacy outcome outside the future confirmatory denominator.
- Selected standard GitHub provenance plus explicitly workflow-authored manifest
  metadata for implementation, while keeping the profile unfrozen and RG-009
  partial.
- Added a separate production v0.2 manifest schema, a versioned production-only
  reason-code extension, and an integrated P3 entry point that refuses to report
  attestation-only success and executes all P1 payload checks.
- Added a hash-bound production result schema that distinguishes P2 from P3,
  requires all six P1 checks for ACCEPT/P3, and constrains REJECT to the
  versioned reason vocabulary. The CLI validates each structured decision before
  emission.
- Preserved that policy, result schema, CLI, adapter, and retained real-P2
  record as byte-identical historical v1 artifacts instead of silently changing
  their semantics.
- Added a non-destructive v2 production line with a closed policy schema, a
  mandatory externally expected policy SHA-256, exact policy-to-policy-schema
  and policy-to-result-schema digest binding, immutable byte rematerialization
  at every API use, and complete contract identity in ACCEPT, REJECT, and ERROR.
- Added 21 v2 adversarial/regression tests covering policy substitution,
  duplicate policy/schema keys, unknown fields, schema substitution,
  frozen-policy cross-field inconsistency, template misuse,
  mutable-dictionary bypass, post-load byte tampering, evidence snapshotting,
  result-schema substitution, library-side output-schema enforcement,
  unbound-output suppression, and exact historical v1 SHA invariants.
- Fixed a direct-execution import-path defect found by an end-to-end CLI check
  and added a subprocess regression test that requires a schema-valid rejection.
- Narrowed source-snapshot assurance to the implemented fact: exact opaque bytes
  are hash-bound, while tar-member equivalence to the separately asserted Git
  tree is explicitly not claimed. This avoids adding an untested custom archive
  proof to the core profile.
- Corrected the selected S1 fixture so its `application/x-tar` snapshot is a
  parseable deterministic USTAR rather than mislabeled text, and moved its
  reserved dependency lock away from every reviewed base path to prevent a
  silent blueprint overwrite.
- Added a closed selected-fixture result schema and a separate six-base R0 run.
  A separate same-worktree validator reconstructs blueprint-plus-fixture payload bytes,
  checks archives/manifests/results, and replays all four profiles; all 24 clean
  rows accepted. This remains controlled-PKI, exploratory, and non-Sigstore.
- Migrated the outcome-unobserved S1 catalog to a selected-profile v0.4 draft:
  all 34 historical IDs are preserved, seven semantic operators are added, and
  the eleven affected provenance/manifest mutations have explicit authenticated
  JSON pointers and P2/P3 ablation expectations. Historical contracts and runs
  remain byte-identical.
- Derived and separately replayed the selected 6 × 41 compatibility product
  (246 units): 185 compatible, 54 pending policy freeze, and 7 structurally
  non-compatible rows—six public-keyless transparency units and one B04
  inventory unit without a unique required-role target. A counterfactual replay that
  poisons every target decision and profile expectation leaves all rows
  unchanged. No adversarial confirmatory case was generated or read.
- Replaced generic hard-coded mutation targets with deterministic base-aware
  plans for all 246 base×operator pairs. Exactly 245 plans resolve; the sole
  unavailable plan is explicitly classified instead of mutating the wrong
  payload. A source-bound `NO-GO` development receipt covers four focused tests
  and 65 disposable target-dependent executions without invoking a verifier or
  creating confirmatory artifacts.
- Hardened the RG-006 synthetic runner contract to retain later unauthorized
  attempts, cross-check process metadata and exact record hashes, bound inherited
  capture-pipe cleanup, and reject source-inventory drift. The retained receipt
  contains 29 tests. A new non-overwriting v2 receipt retains 52 focused tests,
  including exact
  pre-spawn executable/argv/environment/working-root commitments, bounded
  wait/TERM/KILL/reap behavior, sealed-output rereads, and the closed classifier
  projection, atomic platform no-replace rename, inode-bound rereads, bounded
  EINTR handling, twelve ENOSPC/EDQUOT/EIO cells, four transient-EINTR cells,
  three persistent-EINTR cells, three subprocess crash points, and same-UID
  entry-substitution detection. Storage fault coverage remains explicitly
  partial: recovery, all runner persistence boundaries, power-loss durability,
  and cross-filesystem behavior remain open, as do all production/isolation/
  authentication/review controls.
- Added a closed canonical `SCIENTIFIC_INTENT` event and a local sequence-only,
  parent-hashed log gate immediately before the contract-test `Popen`. The
  runner holds a cooperative append lock through spawn, replays every event,
  rejects unknown/gapped/corrupt states, binds the event into process metadata,
  and retains an intent when spawn fails or the parent crashes. Nine focused
  cells bring the active RG-006 suite to 61. The control remains `PARTIAL`:
  authenticated checkpoints, rollback detection, same-UID exclusion, recovery,
  classifier-derived counters, production adapters, and power-loss durability
  are still absent.
- Replaced the selected-profile development receipt v1 with an incompatible
  v2-draft contract requiring identical pre/post RFC 8785 source-inventory
  commitments, strict duplicate-free JSON, a bounded subprocess, schema
  validation before persistence, and explicit inclusion of its runner,
  validator, and schema. The earlier receipt is not relabeled as current.
- Replaced the overbroad label “independent validator” with “separate
  same-worktree validator.” The earlier selected clean-base run was retained;
  a deterministic comparison confirms all 101 base/archive/result files are
  identical to the corrected run while the source snapshots differ as expected.
- Split the selected-profile mutation generator, verifier, oracle renderer, and
  result evaluator into separate modules. The generator now implements all 41
  catalog operators without reading profile expectations or result files.
- Added a schema-closed 164-row draft oracle rendered only from catalog
  expectations, plus a validator that executes no case and records that the
  same-author oracle is neither independently reviewed nor frozen.
- Exercised all 164 case×profile combinations only in disposable development
  fixtures, checked exact changed paths for every operator, checked the single
  authenticated JSON Pointer for each of the eleven semantic mutations, and
  replayed all 41 mutated trees in the same environment. No 6×41 confirmatory
  corpus or case archive was created.
- Preserved `JSON_INVALID` and `DUPLICATE_JSON_KEY` through the integrated P3
  manifest-assertion layer instead of collapsing authenticated malformed JSON
  into the less specific `PROVENANCE_INVALID` code.
- Added a schema-closed release-lineage contract separating A.M.Y, Atlas, AXIOM,
  and study-toolchain labels from exact execution identities. It requires an
  18-field release identity tuple, Git object-format/OID consistency, distinct
  R0 registration identifier/export hash, exact R1 parents, and append-only R2
  correction chains with new bytes/DOIs and no replacement. Its separate
  same-author static validator reads no verifier outcomes or confirmatory
  artifacts and currently reports `NO-GO` with R0 draft and R1/R2 absent.

## 0.3.0-draft — 2026-07-13

- Incorporated the second recorded ten-model review without treating model
  votes as oracle evidence.
- Defined P0 duplicate-key behavior and P2 hashing of raw manifest octets.
- Replaced the detached provenance duplicate with a single normative Sigstore
  DSSE bundle representation.
- Added exact pilot resource limits, path/link/file-type rules, a manifest
  schema, four-state per-check results, and exact 40/64-character Git IDs.
- Expanded the finite catalog to 34 cases, including missing/malformed inputs,
  certificate-time policy, hardlinks, FIFOs, and malformed authenticated
  Statements.
- Added a deterministic, explicitly non-production DSSE/Ed25519/X.509 pilot
  backend and a separate trust root so no current Atlas key is reused.
- Implemented all four profiles, mutation generation, deterministic case/source
  archives, result hashing, schema validation, and the complete pilot matrix.
- Pinned Python dependencies in `uv.lock` and added RFC 8785 and DSSE vectors.
- Added archived contract ledgers and a separate pilot-run validator that
  recomputes result, matrix, archive, policy, source, and contract hashes.
- Kept production GitHub/Sigstore identity, independent human oracle review,
  clean Linux reproduction, and registration as unresolved gates.

## 0.2.0-draft — 2026-07-13

Planned revision after the recorded ten-model exploratory review batch
`exploratory_20260713T044253Z`:

- separate implementation conformance from target security-goal coverage;
- remove pooled FAR and macro-averaged conformance as primary outcomes;
- replace confirmatory “hypotheses” that restated the oracle with explicit
  design requirements and falsification conditions;
- add a signature-only profile matching the observed Atlas failure mode;
- define V0 precisely rather than inferring its behavior case by case;
- move availability, authorized falsehood, compromised builder, and opaque-model
  drift out of the attack corpus into explicit boundaries;
- remove stateful rollback detection from the primary profile until a trusted
  external state mechanism is fixed;
- require exact attestation subject, predicate type, trust policy, reason-code
  taxonomy, and compatibility rules before registration;
- add malformed input, duplicate path/key, symlink, canonicalization, algorithm,
  identity, predicate, and resource-limit cases;
- require independent oracle review before preregistration and confirmatory
  execution.

## 0.1.0-draft — 2026-07-13

- Created the isolated study, baseline audit, initial three-policy protocol,
  threat model, attack catalog, preregistration draft, source ledger, and claim
  ledger.
- Marked every artifact as exploratory and not preregistered.
