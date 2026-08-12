# Verifiable Scientific Release Study

Working title: **From Checksums to Attestations: Evaluating Tamper-Evident
Scientific Releases Under Software and Model Drift**

## Status

- Protocol version: `0.3.0-draft`
- Status: design, exploratory audit, and synthetic pilot only
- Preregistered: **no**
- Confirmatory benchmark started: **no**
- Results suitable for a paper: **no**
- Registration decision: **NO-GO** (`10/14` blocking gates incomplete;
  machine-readable registry is authoritative)
- Latest locally retained pilot: `pilot_runs/pilot_20260713T054931Z` (**not
  committed, not public-packet material, and not confirmatory**); its committed
  bounded digest/count record is
  `pilot_runs/PILOT_RETENTION_SUMMARY_2026-07-18.json`
- Selected-profile clean-base R0:
  `selected_profile_base_runs/r0_selected_bases_20260713T101851Z` (**24/24
  clean profile checks accepted under controlled public test PKI; not
  confirmatory and not production Sigstore**)
- Real-crypto interoperability smoke:
  `production_pilot_runs/github_cli_2.96.0_upstream_smoke` (**P2 only; not
  A.M.Y and not confirmatory**)
- Current production contract: schema-closed v2 policy/API with mandatory
  external policy SHA-256; the retained policy is still an unusable
  release-template and no A.M.Y P3 result exists

This directory starts a new study. It does not treat existing A.M.Y, Atlas, or
AXIOM documentation as evidence. Every eventual paper claim must point to raw
data, executable analysis, a cryptographically identified release artifact, or
a primary external source.

The word *verifiable* is deliberately bounded. The project can make files,
computations, source revisions, and release identities independently
checkable. It cannot prove that an authorized author is honest, that a cloud
model provider did not change an undisclosed backend, or that a scientific
interpretation is true merely because a package has a valid signature.

## Study structure

| Path | Purpose |
|---|---|
| `audit/BASELINE_AUDIT_2026-07-13.md` | Reproducible exploratory audit of the current A.M.Y/Atlas state |
| `audit/ATLAS_DEEP_CODE_AND_ARTIFACT_AUDIT_2026-07-13.md` | Deep ATLAS code/artifact findings with bounded claim language |
| `audit/ATLAS_DEEP_AUDIT_RAW_2026-07-13.json` | Machine-readable output of the read-only ATLAS scanner |
| `audit/ATLAS_DEEP_AUDIT_VALIDATION_2026-07-13.json` | Same-environment canonical replay check for the ATLAS audit |
| `audit/AXIOM_DEEP_AUDIT_RAW_2026-07-13.json` | Read-only AXIOM boundary, producer, retained-artifact, and claim audit |
| `audit/AXIOM_DEEP_AUDIT_VALIDATION_2026-07-13.json` | Same-environment canonical replay check for the AXIOM audit |
| `audit/AXIOM_DEEP_CODE_ARTIFACT_AND_PAPER_AUDIT_2026-07-13.md` | Human-readable AXIOM executable-boundary, artifact, and paper-evidence findings |
| `audit/AMY_DEEP_AUDIT_RAW_2026-07-13.json` | Read-only A.M.Y provenance, manifest, watermark, and integrity audit |
| `audit/AMY_DEEP_AUDIT_VALIDATION_2026-07-13.json` | Same-environment canonical replay check for the A.M.Y audit |
| `audit/AMY_SYSTEM_PAPER_CODE_DATA_PDF_AUDIT_2026-07-13.md` | Deep audit of the formal paper's code, data, inference, release, and rendered PDF |
| `audit/AMY_SYSTEM_PAPER_DEEP_AUDIT_RAW_2026-07-13.json` | Machine-readable recomputation of both committed and dirty paper-release states |
| `audit/AMY_SYSTEM_PAPER_DEEP_AUDIT_VALIDATION_2026-07-13.json` | Canonical replay and accounting validation for the formal-paper audit |
| `audit/LATEST_MANUSCRIPTS_CODE_DATA_PDF_AND_REFERENCE_AUDIT_2026-07-13.md` | Deep admissibility audit of the latest legacy A.M.Y, ATLAS, AXIOM, DNA, and bond-energy manuscripts plus their PDF/reference boundaries |
| `audit/LATEST_MANUSCRIPTS_DEEP_AUDIT_RAW_2026-07-13.json` | Deterministic current-byte, source-to-claim, provenance, artifact, and curated primary-reference record for those manuscripts |
| `audit/LATEST_MANUSCRIPTS_DEEP_AUDIT_VALIDATION_2026-07-13.json` | Same-environment canonical replay check for the latest-manuscript audit |
| `audit/UPSTREAM_ATTESTATION_SEMANTICS_2026-07-13.json` | Exact pinned `actions/attest` source/dependency hashes and the observed default-predicate/P3 mismatch |
| `audit/SELECTED_ATTESTATION_PROFILE_IMPLEMENTATION_AUDIT_2026-07-13.md` | Human-readable audit of the selected profile, output contract, synthetic boundary, opaque snapshot scope, and remaining blockers |
| `audit/SELECTED_ATTESTATION_PROFILE_AUDIT_RAW_2026-07-13.json` / `audit/SELECTED_ATTESTATION_PROFILE_AUDIT_VALIDATION_2026-07-13.json` | Preserved historical selected-profile audit pair; subsequent source changes make it non-active |
| `audit/SELECTED_ATTESTATION_PROFILE_AUDIT_RAW_2026-07-15.json` / `audit/SELECTED_ATTESTATION_PROFILE_AUDIT_VALIDATION_2026-07-15.json` | Preserved historical selected-profile audit pair; subsequent runner-source changes make it non-active |
| `audit/SELECTED_ATTESTATION_PROFILE_AUDIT_RAW_V2_2026-07-15T034921Z.json` | Last dated deterministic static/code-contract record for the selected profile; retained as historical because later registration-gate changes produce explicit current drift |
| `audit/SELECTED_ATTESTATION_PROFILE_AUDIT_VALIDATION_V2_2026-07-15T034921Z.json` | Original same-environment canonical replay of that timestamped historical audit; not a claim that present bytes still match |
| `audit/RELEASE_IDENTITY_VERSION_SHA_SIGNATURE_AUDIT_2026-07-13.md` | Cross-system analysis of beta-version identity, Git OIDs, SHA-256 scope, observed signatures, Sigstore policy boundaries, and R0→R1→R2 release rules |
| `protocol/PROTOCOL_DRAFT.md` | Research questions, design, endpoints, and analysis |
| `protocol/THREAT_MODEL.md` | Assets, trust boundaries, adversaries, and non-goals |
| `protocol/PATH_POLICY_DRAFT.md` | Exact draft portable-path and filesystem rules |
| `protocol/ATTACK_CATALOG.json` | Immutable historical v0.3 34-case pilot catalog; retained runs continue to bind these exact bytes |
| `protocol/ATTACK_CATALOG_SELECTED_PROFILE_DRAFT.json` | Outcome-unobserved v0.4 selected-profile catalog with all 34 historical IDs plus seven new semantic operators (41 total) |
| `protocol/ATTACK_CATALOG_SELECTED_PROFILE_VALIDATION.json` | Deterministic migration replay, historical-ID preservation, fixture-implementation, and no-confirmatory-access checks |
| `protocol/SELECTED_PROFILE_ORACLE_DRAFT.json` | Schema-closed 164-row draft oracle rendered only from the selected catalog; same-author, unreviewed, and unfrozen |
| `protocol/SELECTED_PROFILE_ORACLE_VALIDATION.json` | Deterministic catalog-only oracle replay and static generator/verifier/oracle/evaluator separation check; executes no cases |
| `paper/MANUSCRIPT_SKELETON.md` | Pre-R1 manuscript with sourced background, protocol-aligned introduction/methods/threat model/limitations, and mechanically locked abstract/results/discussion/conclusion |
| `paper/lint_manuscript.py` | Stage linter rejecting gated-section escapes, forbidden claim shortcuts, unresolved citations, and unknown/missing source-ledger references |
| `reviews/R0_REVIEW_PACKET_DRAFT.md` | Fail-closed instructions for a future SHA-bound review by a qualified non-implementer; explicitly preparation-only |
| `protocol/R0_HUMAN_REVIEW_RECORD_TEMPLATE.json` | Unreviewed template covering 41 catalog cases, 164 oracle rows, 12 propositions, 246 compatibility rows, 7 policy decisions, and one manuscript-consistency decision |
| `protocol/R0_REVIEWER_IDENTITY_POLICY_TEMPLATE.json` | Unusable preauthorization template for one exact reviewer identity, OIDC issuer, trusted root, non-vulnerable pinned Cosign binary, and offline verification flags |
| `protocol/R0_REVIEWER_IDENTITY_POLICY_VALIDATION.json` | Static validation of that template; reports internally valid `NO-GO`, reads no record/bundle/outcome, and cannot close RG-004 |
| `development_checks/SELECTED_PROFILE_FULL_GENERATOR_ORACLE_2026-07-13.json` / `development_checks/SELECTED_PROFILE_FULL_GENERATOR_ORACLE_VALIDATION_2026-07-13.json` | Preserved historical selected-profile development pair; later runner-source changes make it non-active |
| `development_checks/SELECTED_PROFILE_FULL_GENERATOR_ORACLE_2026-07-15.json` / `development_checks/SELECTED_PROFILE_FULL_GENERATOR_ORACLE_VALIDATION_2026-07-15.json` | Preserved historical selected-profile development pair; subsequent runner-source changes make it non-active |
| `development_checks/SELECTED_PROFILE_FULL_GENERATOR_ORACLE_V2_2026-07-15T034921Z.json` | Active v2-draft same-author receipt for six development tests covering 41 operators and 164 case×profile evaluations, with equal pre/post source-inventory commitments |
| `development_checks/SELECTED_PROFILE_FULL_GENERATOR_ORACLE_VALIDATION_V2_2026-07-15T034921Z.json` | Active strict JSON/schema, current-source, pre/post-inventory, stdout/stderr, count, and non-confirmatory-boundary validation for the timestamped execution record |
| `protocol/ROBUSTNESS_CATALOG_DRAFT.json` | Separate pre-registration TOCTOU/fault-injection engineering stratum, excluded from primary denominators |
| `protocol/VERSIONING_AND_SIGNING_POLICY.md` | Rules for beta software, SHA-256, signatures, tags, and DOI releases |
| `protocol/RELEASE_LINEAGE_CONTRACT_DRAFT.json` | Schema-closed A.M.Y/Atlas/AXIOM/study-toolchain identity and R0→R1→R2 contract; R0 has separate registration identifier/export hash, Git OID lengths follow the declared object format, R2 corrections are append-only, and freeze remains forbidden |
| `protocol/RELEASE_LINEAGE_VALIDATION.json` | Hash-bound same-author static validation of the lineage contract; reads no verifier result or confirmatory artifact and reports `NO-GO` |
| `protocol/GITHUB_ATTESTATION_POLICY_TEMPLATE.json` | Byte-preserved historical v1 policy used by the retained real-P2 smoke; not the current production contract |
| `protocol/GITHUB_ATTESTATION_POLICY_TEMPLATE_V2.json` | Current schema-closed production policy template with immutable numeric repository/owner identities; deliberately unusable until release-specific values and authenticated workflow bytes replace every TBD |
| `protocol/ATTESTATION_PROFILE_DECISION_DRAFT.json` | Pre-registration selection record for standard GitHub provenance plus authenticated manifest metadata; implementation and independent review remain unfrozen |
| `protocol/PRODUCTION_SIGSTORE_GATE_DRAFT.md` | Production verification sequence, exact tool/action pins, and negative controls |
| `protocol/REGISTRATION_GATES.json` | Machine-readable GO/NO-GO requirements and retained evidence paths |
| `protocol/PRE_R0_CLOSURE_LEDGER.json` | SHA-bound `NO-GO` map of the 10 blocking gates, 17 unmet evidence requirements, prohibited inferences, external-actor dependencies, and exact acceptance tests |
| `protocol/PRE_R0_CLOSURE_LEDGER_VALIDATION.json` | Same-worktree structural replay of the closure ledger: 10 controls, matching bindings, and zero scientific authorization |
| `protocol/ARTIFACT_RETENTION_POLICY.json` | Explicit status, validator, source-Git, and public-packet policy for every retained audit, run, and review root |
| `protocol/ARTIFACT_RETENTION_INDEX.jcs.json` | Canonical deterministic tree digests plus coverage and absolute-path checks; byte identity only, not authentication or scientific validation |
| `scripts/build_artifact_retention_index.py` | Rebuilds the retained index, rejects unindexed files and overlapping entries, and forbids public-packet selection when absolute filesystem paths are present |
| `protocol/MODEL_REVIEW_PROTOCOL.json` | Frozen exploratory ten-slot Ollama Cloud review design with distinct roles, exact source-byte commitments, one attempt per slot, no voting, no replacement, and closed response grammar |
| `schemas/model-review-protocol.schema.json` / `schemas/model-review-response.schema.json` | Closed schemas for the review design and admissible advisory responses |
| `scripts/run_model_review_batch.py` / `scripts/validate_model_review_batch.py` | Parallel no-retry runner and strict retained-batch validator; model findings never authorize scientific claims |
| `reviews/model_review_20260713T225218Z/` | Local-only raw ten-slot transport-failure attempt; excluded from source Git and the public packet because it contains prompts and source snapshots. Tests construct an equivalent failure fixture without treating it as scientific evidence |
| `protocol/PROPOSITION_MATRIX_DRAFT.json` | RQ-to-unit-to-outcome-to-falsification-to-permitted-claim contract; complete draft pending independent review/freeze |
| `protocol/RUN_EXECUTION_POLICY_DRAFT.json` | Closed draft binding 16 runner/schema/test/lock inputs by SHA-256; retry requires one typed pre-intent predicate and a persisted attempt-one classification hash |
| `protocol/RUN_EXECUTION_POLICY_VALIDATION.json` | Design-only replay: all bound hashes and the active retained 61-test v3 receipt match. The suite includes bounded waits, pre-spawn commitments, a hash-chained local scientific-intent event, sealed-output rereads, fail-closed classifier projections, bounded `EINTR`, injected `ENOSPC`/`EDQUOT`/`EIO`, same-UID entry substitution, and process-crash publication states. Scientific-intent and storage-fault controls remain only `PARTIAL`; confirmatory permission and RG-006 completion remain false |
| `protocol/CONFIRMATORY_RUNNER_CONTRACT_DRAFT.md` | State machine, 12-cell attempt table, campaign-wide pre-decode seal, denominator mapping, implemented primitive, and explicit production limitations |
| `development_checks/RG006_RUNNER_CONTRACT_TEST_2026-07-13.json` | Byte-preserved historical v1 synthetic receipt for 29 passing runner tests; it is not the active RG-006 receipt |
| `development_checks/RG006_RUNNER_CONTRACT_TEST_V2_2026-07-14.json` | Preserved historical v2 candidate for 52 passing tests over its then-bound source inventory; later contract-document corrections make it non-active without altering its bytes |
| `development_checks/RG006_RUNNER_CONTRACT_TEST_V2_2026-07-15.json` | Preserved historical non-overwriting v2 receipt for 52 passing runner tests; subsequent scientific-intent changes make it non-active without altering its bytes |
| `development_checks/RG006_RUNNER_CONTRACT_TEST_V3_2026-07-15.json` | Preserved first v3 candidate; the then-current 16-binding policy was rejected by the previous policy schema, so this receipt never became active |
| `development_checks/RG006_RUNNER_CONTRACT_TEST_V3_2026-07-15T034827Z.json` | Preserved valid v3 candidate superseded after correcting the runner-contract boundary wording; its bytes remain unchanged |
| `development_checks/RG006_RUNNER_CONTRACT_TEST_V3_2026-07-15T034921Z.json` | Active non-overwriting, pre/post-source-bound v3 receipt for 61 passing runner tests. Its control map keeps all eleven production controls open and classifies scientific intent and crash/storage fault injection only `PARTIAL`; same-UID exclusion, rollback/suffix deletion detection, authenticated checkpointing, recovery, power-loss durability, cross-filesystem equivalence, classifier derivation, production-adapter integration, and complete runner-wide persistence coverage remain unestablished |
| `development_checks/BASE_AWARE_MUTATION_PLANS_2026-07-13.json` / `development_checks/BASE_AWARE_MUTATION_PLANS_VALIDATION_2026-07-13.json` | Preserved historical base-aware receipt and validation; later runner-source changes make this pair non-active without altering its bytes |
| `development_checks/BASE_AWARE_MUTATION_PLANS_2026-07-15.json` / `development_checks/BASE_AWARE_MUTATION_PLANS_VALIDATION_2026-07-15.json` | Preserved historical base-aware pair; subsequent runner-source changes make it non-active without altering its bytes |
| `development_checks/BASE_AWARE_MUTATION_PLANS_V2_2026-07-15T034921Z.json` | Active pre/post-source-bound `NO-GO` receipt for all 246 base×operator plan resolutions and 65 disposable target-dependent executions; no verifier, oracle, result ledger, or confirmatory archive was used |
| `development_checks/BASE_AWARE_MUTATION_PLANS_VALIDATION_V2_2026-07-15T034921Z.json` | Active separate same-worktree validation, including 245 resolved plans and the one exact unavailable B04 plan |
| `dummy_analysis/DUMMY_OBSERVATION_LEDGER.json` | Full 1,480-row synthetic compatible-unit×profile×environment ledger built from the authoritative catalog, compatibility matrix, and oracle; contains predeclared failure/mismatch injections and no confirmatory evidence |
| `dummy_analysis/DUMMY_ANALYSIS_SUMMARY.json` | Deterministic dummy analysis with authoritative-input hashes, exact product/pairing checks, five-category denominator accounting, profile×family target-invalid breakdowns, explicit non-evaluable propositions, and zero manuscript authorization |
| `corpus/BASE_REGISTRY_DRAFT.json` | Six deterministic, redistributable S1 clean-base blueprints; expected R0 hashes intentionally null until freeze |
| `protocol/PREREQUISITE_REGISTRY_DRAFT.json` | Historical v0.3 structural prerequisite registry |
| `protocol/PREREQUISITE_REGISTRY_SELECTED_PROFILE_DRAFT.json` | Selected-profile structural prerequisite registry with explicit unresolved policy-freeze states |
| `corpus/COMPATIBILITY_MATRIX_DRAFT.json` | Immutable historical 204-row base×operator matrix |
| `corpus/COMPATIBILITY_MATRIX_VALIDATION.json` | Historical matrix completeness and outcome-blinding validation |
| `corpus/COMPATIBILITY_MATRIX_SELECTED_PROFILE_DRAFT.json` | Complete selected-profile 246-row matrix: 185 compatible, 54 pending, and 7 structurally non-compatible rows (six public-keyless transparency units plus one B04 inventory mutation without a unique required-role target) |
| `corpus/COMPATIBILITY_MATRIX_SELECTED_PROFILE_VALIDATION.json` | Separate same-worktree clean-base/prerequisite replay, deterministic reconstruction, and counterfactual outcome-blinding check |
| `corpus/README.md` | Base/case timing boundary, strata, retained failed attempt, and valid exploratory base pilot |
| `protocol/CLAIM_BOUNDARIES.md` | Language and evidence rules that prevent overclaiming |
| `protocol/LIMITATIONS_AND_BOUNDARIES.md` | Threats that signatures/checksums cannot resolve and that are excluded from benchmark scores |
| `protocol/REASON_CODES.json` | Machine-readable verifier outcome vocabulary and precedence |
| `protocol/PRODUCTION_REASON_CODES_DRAFT.json` | Versioned production-only reason-code extension that preserves the retained v0.3 pilot vocabulary and hashes |
| `schemas/verifier-result.schema.json` | Draft 2020-12 result contract |
| `schemas/manifest.schema.json` | Draft closed-world content-manifest contract |
| `schemas/manifest-production-v0.2.schema.json` | Selected production-manifest draft with explicit workflow-authored build metadata cross-bound to source/lock payloads |
| `schemas/github-production-verification-result.schema.json` | Byte-preserved historical v1 terminal-result contract |
| `schemas/github-attestation-policy-v2.schema.json` | Closed current-policy grammar, including a distinct template state, immutable numeric repository/owner IDs, and stricter frozen-policy fields |
| `schemas/github-production-verification-result-v2.schema.json` | Current terminal-result contract; every structured result binds policy, policy-schema, and result-schema SHA-256, and P3 acceptance requires all six P1 checks |
| `schemas/selected-profile-fixture-result.schema.json` | Closed result contract for the controlled selected-profile S1 fixture; explicitly not a production Sigstore result |
| `schemas/selected-profile-oracle.schema.json` | Closed draft contract for 41 cases × 4 profile expectations; forbids observed-result fields |
| `schemas/selected-profile-development-check.schema.json` | Closed v2-draft receipt contract requiring equal pre/post source-inventory commitments for the disposable-fixture execution; all production/confirmatory/review claims are false |
| `schemas/base-aware-mutation-development-check.schema.json` | Closed `NO-GO` receipt contract for base-aware mutation planning and disposable target-fidelity checks, with pre/post source-inventory equality |
| `schemas/release-lineage-contract.schema.json` | Closed contract for software/toolchain identities, immutable stage records, exact parent references, Git object-format/OID consistency, the 18-field release identity tuple, and append-only R2 corrections |
| `schemas/release-lineage-validation.schema.json` | Closed output contract for static lineage validation and its no-outcome/no-network boundary |
| `schemas/run-execution-policy.schema.json` | Closed grammar for timeouts, attempts, infrastructure predicates, missingness, deviations, and external reproduction |
| `schemas/run-execution-policy-validation.schema.json` | Closed design-validation result contract for the run policy |
| `schemas/process-isolation-record.schema.json` | Closed synthetic subprocess record with a mandatory scientific-intent receipt; records rather than overstates absent network/filesystem/process-tree isolation |
| `schemas/scientific-intent-event.schema.json` | Closed canonical local pre-spawn event contract binding sequence, parent event, spawn identifier, argv/environment/stdin/output commitments, policy hash, and explicit false durability/adversary boundaries |
| `schemas/environment-attempt-record.schema.json` | Outcome-free attempt contract with intent counters, parent authorization, raw commitments, and false production limitations |
| `schemas/infrastructure-classification.schema.json` | Pre-decode `RETRY_ELIGIBLE`/`NOT_RETRY_ELIGIBLE`/`INVALID_CLASSIFICATION` record bound to the attempt and classifier projection |
| `schemas/official-attempt-selection.schema.json` | Two-environment campaign seal retaining unauthorized attempts and forbidding decode authorization without later external authentication |
| `schemas/pre-r0-closure-ledger.schema.json` | Closed planning-evidence contract separating established facts from prohibited inferences and unmet closure evidence |
| `schemas/pre-r0-closure-ledger-validation.schema.json` | Closed same-worktree validation contract that remains `NO-GO` even when structurally valid |
| `schemas/rg006-contract-test-record.schema.json` | Byte-preserved historical v1 NO-GO receipt schema for the 29-test runner contract receipt |
| `schemas/rg006-contract-test-record-v2.schema.json` | Preserved historical v2 receipt schema requiring its exact 52-test coverage map and false power-loss/recovery/cross-filesystem boundaries |
| `schemas/rg006-contract-test-record-v3.schema.json` | Active closed v3 receipt schema requiring the exact 61-test coverage map, explicit `PARTIAL` scientific-intent/storage controls, all eleven production controls open, and false authenticated-checkpoint/rollback/recovery/classifier-derivation boundaries |
| `schemas/observation-ledger.schema.json` | Closed row-level contract for planned finite-corpus observations and explicit generation/missing/terminal states |
| `schemas/analysis-summary.schema.json` | Closed output contract for category totals, proposition decisions, and manuscript-eligibility boundaries |
| `schemas/r0-human-review-record.schema.json` | Closed template/submission contract for exact-byte human review; schema validity alone cannot establish reviewer authorization or truth |
| `schemas/r0-review-packet-verification.schema.json` | Closed result contract for mechanical packet verification with all signature/authorization/competence/RG-004 claims fixed false |
| `schemas/r0-reviewer-identity-policy.schema.json` | Closed template/frozen grammar separating reviewer preauthorization from later signature verification |
| `schemas/r0-reviewer-identity-policy-validation.schema.json` | Closed static-validation result contract with `rg004_complete` fixed false |
| `amy_verifier/` | Separate selected-profile mutation generator, verifier fixture, catalog-only oracle, result evaluator, byte-preserved historical v1 core, non-injectable v2 production core/wrapper, and a synthetic-only confirmatory-runner contract primitive |
| `amy_verifier/github_attestation_v2_core.py` | Current v2 production core; invokes the pinned verifier directly, binds numeric repository/owner identities, rejects v1 evidence objects, and refuses to treat dependency pins as authenticated workflow-byte evidence |
| `scripts/audit_atlas_integrity.py` | Read-only scanner; does not import ATLAS, load pickle, or read private-key bytes |
| `scripts/audit_system_paper_integrity.py` | Read-only release/scorer/statistics audit; does not contact Ollama or mutate the paper worktree |
| `scripts/audit_latest_manuscripts.py` | Read-only current-byte audit of recent manuscripts, cited evidence, producer links, and curated reference metadata |
| `scripts/verify_github_attestation.py` | Byte-preserved historical v1 CLI retained for the real-P2 smoke |
| `scripts/verify_github_attestation_v2.py` | Current production CLI; requires an external expected-policy SHA-256, verifies both schema digests, suppresses unbound JSON, and validates every structured result |
| `scripts/validate_release_lineage_contract.py` | Computes lineage consistency and freeze permission from the contract without reading bundles, verifier outcomes, or confirmatory evidence |
| `scripts/validate_run_execution_policy.py` | Replays policy/schema/hash/count/C011 invariants without reading or joining any confirmatory outcome |
| `scripts/validate_claim_evidence_matrix.py` | Fail-closed validation of exact claim evidence paths, locators, and raw SHA-256 values; resolves references mechanically but never authorizes scientific claims |
| `scripts/validate_pre_r0_closure_ledger.py` | Rejects stale bindings, gate drift, missing evidence paths, duplicate JSON names, and summary drift without reading confirmatory evidence |
| `scripts/run_rg006_contract_tests.py` | Verifies typed policy bindings, inventories sources before and after, runs only the 61 synthetic runner tests, and creates the active v3 `NO-GO` receipt exclusively with file and parent-directory synchronization; it refuses to overwrite an existing receipt |
| `scripts/run_base_aware_mutation_development_check.py` | Runs only the four base-aware planning/target-fidelity tests with pre/post source inventory and emits a retained `NO-GO` receipt |
| `scripts/validate_base_aware_mutation_development_check.py` | Separately checks the base-aware receipt schema, source hashes, output hashes, coverage counts, and non-confirmatory boundaries |
| `scripts/build_dummy_analysis_fixture.py` | Builds the complete current synthetic analysis product from outcome-blind compatibility and oracle contracts |
| `scripts/analyze_observation_ledger.py` | Rejoins every copied ledger label to the authoritative catalog/matrix/oracle, enforces the exact unit×environment×profile product and cross-profile archive pairing, and evaluates only propositions supported by recorded observables |
| `scripts/build_r0_review_packet.py` | Builds a deterministic JCS/USTAR review packet from explicit sources plus exact allowlisted base-aware and RG-006 `NO-GO` receipts; empirical/confirmatory outputs remain forbidden |
| `scripts/verify_r0_review_packet.py` | Verifies externally supplied manifest/packet SHA-256 values, JCS, USTAR members, and optional record binding; does not verify a signature or reviewer |
| `scripts/validate_r0_reviewer_identity_policy.py` | Rejects ambiguous JSON, missing sources/flags, unsupported major versions, and Cosign versions below patched 2.6.2/3.0.4 floors without executing authentication |
| `scripts/audit_selected_attestation_profile.py` | Read-only AST/schema/retained-record audit of the selected production profile; it invokes neither GitHub CLI nor Sigstore |
| `pilot_runs/` | Immutable exploratory runs and their validation records |
| `production_pilot_runs/` | Retained real-cryptography interoperability checks, kept separate from confirmatory evidence |
| `base_pilot_runs/` | Exploratory R0 clean-base builds; contains no derived confirmatory mutation cases |
| `selected_profile_base_runs/` | Separate selected-profile R0 clean-base evidence; six bases and 24 clean profile results, with no adversarial cases |
| `selected_profile_base_runs/SELECTED_RUN_COMPARISON_2026-07-13.json` | Same-environment comparison retaining the pre-terminology and corrected runs; all 101 base/archive/result files are identical while source snapshots differ |
| `selected_profile_base_runs/R0_SELECTED_BASES_CURRENT_REPLAY_2026-07-13.json` | Current same-worktree replay: retained run internally valid and clean behavior unchanged, with explicit post-run source drift at three paths |
| `robustness_runs/` | Retained pre-registration TOCTOU/fault-injection engineering runs, excluded from confirmatory evidence |
| `preregistration/OSF_PREREGISTRATION_DRAFT.md` | Draft to freeze before confirmatory runs |
| `evidence/SOURCE_LEDGER.md` | Primary standards and policies, with the exact fact each supports |
| `evidence/CLAIM_EVIDENCE_MATRIX.csv` | Forty-seven-claim ledger with canonical exact-path, locator, and SHA-256 references for the 40 currently allowed bounded claims; seven non-authorized claims remain empty |

## Required gates

1. Make every blocking entry in `protocol/REGISTRATION_GATES.json` complete and
   resolve every `TBD-BEFORE-REGISTRATION` item.
2. Keep mutation generation, oracle generation, result evaluation, and the four
   verifier profiles in separate modules; obtain a signed exact-byte review by
   a qualified non-implementer, resolve findings, and only then freeze them.
3. Run only synthetic pilot fixtures; use the pilot to find implementation
   defects, not to estimate or tune confirmatory effects.
4. Freeze the protocol, attack catalog, schemas, analysis code, and expected
   decision rules. Record their SHA-256 digests.
5. Submit the frozen protocol to a time-stamped, read-only registry.
6. Create the confirmatory corpus without changing the registered rules.
7. Run the benchmark once, retaining all failures and all raw logs.
8. Reproduce the complete released benchmark through a qualified external
   non-implementer before manuscript submission; same-author clean replay is
   insufficient.
9. Obtain an independent artifact audit before making a release claim.
10. Publish a new immutable release for every correction; never replace files
    inside an already identified release.

## Role of language models

The frozen exploratory design in `protocol/MODEL_REVIEW_PROTOCOL.json` assigns
ten distinct Ollama Cloud labels to cryptography, implementation, security,
claim consistency, experimental design, open science, supply chain, systems,
model drift, and statistics. It reviews 49 exact source files, including code,
tests, schemas, audits, and manuscript-facing contracts. Outputs are advisory
records, not ground truth. A model may
propose an attack or identify an ambiguity, but it may not:

- decide the expected label of a confirmatory test;
- create a citation that is accepted without checking the primary source;
- silently rewrite a hypothesis after results are visible;
- be described as bitwise reproducible when its weights or serving backend are
  not available;
- serve as the sole reviewer of a scientific or cryptographic claim.

Every model call used in the research record must retain the exact request and
response bytes, model label, Ollama client and server versions, parameters,
timestamps, and errors. Provider-opaque model internals must be reported as an
explicit limitation. Slots execute concurrently, once per batch, without
replacement, retry, majority vote, or silent omission. A later successful batch
must receive a new batch identity; it cannot overwrite the retained failed
2026-07-13 attempt, whose ten calls were denied before HTTP response by the
current sandbox. That attempt produced no model review and no findings.

## Pilot warning

The synthetic pilot uses a deterministic public test PKI and a custom
`application/vnd.amy.pilot-fixture...` bundle solely to exercise DSSE, certificate,
identity, transparency, subject, provenance, and payload checks. Its signing
material is intentionally reproducible and has no secrecy or production trust.
It is not a Sigstore-conformance result and cannot replace a real GitHub Actions
keyless attestation, archived trusted roots, clean Linux reproduction, or
independent oracle review.

The selected development generator exercises all 41 catalog operators on
temporary generic fixtures. A second base-aware development layer resolves all
246 base×operator plans without consulting outcomes: 245 resolve and exactly
`B04-SOFTWARE × INVENTORY-OMIT-ROLE-001` is unavailable because the required
role is not unique. Its 164 case×profile checks, same-environment tree replays,
and 65 disposable target-dependent executions are unit-test observations only:
they do not instantiate the registered corpus, resolve 54 pending compatibility
rows, or supply a confirmatory denominator. The 164-row oracle is a
deterministic rendering of same-author catalog expectations and remains invalid
for registration until a qualified non-implementer reviews and signs it.

The retained GitHub CLI smoke closes only a narrower interoperability question:
the production adapter can authenticate one genuine public bundle offline under
a pinned tool, trusted root, certificate identity, source revision, and Rekor
requirement. It does not authenticate an A.M.Y release, exercise P3 provenance
semantics, supply a confirmatory denominator, or constitute independent
reproduction.
