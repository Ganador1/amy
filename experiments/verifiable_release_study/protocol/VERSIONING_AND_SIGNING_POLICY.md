# Versioning and Signing Policy

Version: `0.3.0-draft`

## 1. Four distinct identities

Never use one string such as `1.0.0` to stand for:

1. **Software version** — moving A.M.Y/Atlas API/package state.
2. **Source identity** — exact Git object/tree plus exported source bytes.
3. **Study identity** — frozen protocol, corpus, oracle, and analysis.
4. **Publication identity** — immutable paper-plus-artifact deposit.

Beta software may change often without rewriting history: every run points to
the exact source/environment it used, and every prior deposit remains available.
"Latest" is never an execution identity.

## 2. Beta software rules

- A new package identity may use SemVer `0.y.z` while its public contract is
  unstable. The new `amy-verifiable-release-study` package follows this rule.
- Existing A.M.Y already published `v1.0.0`. The same package identity must not
  move backward to `0.y.z` or replace that tag. A breaking experimental line
  under the same identity should use a later prerelease such as
  `2.0.0-alpha.1`; alternatively, a genuinely new package/distribution identity
  may start at `0.1.0` while the legacy release remains visible.
- Python development builds may use PEP 440 forms such as `0.4.0.dev17`.
- Increment package versions according to the declared public interface, but do
  not use the package version as the execution identity.
- Every run records:
  - full Git object ID and Git tree ID;
  - dirty flag;
  - SHA-256 of exact exported source-snapshot bytes, with the snapshot assurance
    stated separately;
  - patch/content snapshot for retained exploratory dirty runs;
  - declared A.M.Y, Atlas, and AXIOM package versions, using an explicit
    not-applicable value when a component is absent from the run;
  - dependency lock and execution-image digests;
  - command, configuration, seed, locale, timezone, and tool versions.
- Official releases require a clean source tree.

SemVer/PEP 440 labels order releases and communicate a declared compatibility
contract. They do not identify execution bytes. A full source commit, exported
source SHA-256, lock digest, and execution-image digest remain mandatory.

This repository currently uses Git SHA-1 object IDs. Record them accurately as
Git identifiers and separately record SHA-256 over exported source bytes. They
identify different data models and must not be relabeled as one another.

## 3. Protocol, corpus, and paper versions

- Draft protocol: `protocol-v0.x.y-draft`.
- Frozen registration: `protocol-v1.0.0` plus registry identifier/DOI.
- Confirmatory corpus: `corpus-v1.0.0` plus deterministic archive SHA-256.
- Paper artifact release: `paper-v1.0.0` or later.
- A correction creates a new version; no published bytes are replaced.
- Cite a version-specific DOI for every claim. A concept DOI may group versions
  but cannot identify the exact bytes used by an analysis.

The study uses three immutable lineage stages rather than pretending one commit
can be known before and after seeing confirmatory results:

1. **R0 registration release:** frozen protocol, bases, generator, oracle,
   compatibility matrix, seeds, analysis code, and environment.
2. **R1 evidence release:** corpus and raw results generated after registration
   by R0, plus deviations and execution logs. R1 cites R0 by exact digest/DOI.
3. **R2 paper release:** manuscript, generated tables/figures, and claim ledger
   derived from R1. R2 cites both R0 and R1.

A bug fix that can affect confirmatory outcomes creates a new implementation and
new registration/evidence lineage; it cannot silently overwrite R0 or R1.

`RELEASE_LINEAGE_CONTRACT_DRAFT.json` makes these rules machine-checkable. A
frozen stage identity is not its SemVer/tag label: it is an 18-field tuple that
includes the explicitly labeled Git object format and commit/tree OIDs, exact
source-snapshot, lock, image, payload-manifest, attestation-policy, trusted-root,
bundle, verifier, result-schema, and transport-archive digests, plus a
version-specific DOI and publication time. R1 must cite the external digest of
the exact R0 record and R2 must cite the exact R0 and R1 records. The record has
no self-hash field; its SHA-256 is carried by external deposit metadata and by
child references. The current retained validation reports `NO-GO`, all three
software identities unresolved, R0 draft, and R1/R2 not created.

## 4. Release directory and manifest

The logical release contains:

```text
MANIFEST.jcs.json
attestation.sigstore.json
payload/...
```

The Sigstore bundle is the sole normative attestation representation. It
contains one DSSE envelope whose base64 payload is the authenticated in-toto
Statement plus the verification material needed by the frozen profile. A
human-readable extracted Statement may be published as a derived convenience
file, but it is not a verifier input and no claim may depend on it.

The manifest:

- is RFC 8785 JCS over the frozen schema;
- enumerates a closed-world set of payload regular files using normalized
  portable relative paths;
- contains full lowercase SHA-256, byte size, media type, and semantic role;
- rejects duplicate keys/paths, absolute/parent paths, symlinks, and escapes;
- excludes itself, provenance, signatures, and attestations from its payload
  list;
- contains no field claiming to hash itself.

The retained synthetic pilot's v0.1 manifest remains an immutable historical
contract. The selected production v0.2 manifest additionally requires a
schema-closed `build_metadata` object labeled
`workflow-authored-not-independently-certified`. It records source commit/tree,
dirty state, an opaque source-snapshot digest, dependency lock, and execution
image. Snapshot and lock metadata are cross-bound to payload entries; P1/P3
still recompute the actual payload bytes. Production v0.2 expressly makes no
package-only claim that the tar members reconstruct the declared Git tree.

Manifest canonicality supports deterministic generation and cross-tool
comparison. Authentication binds the SHA-256 of the exact manifest bytes, so a
verifier does not silently parse and reserialize the manifest before checking
its authenticated subject.

## 5. Attestation subject and predicate

- in-toto Statement `_type`: the frozen Statement v1 value.
- Subject: one named subject whose `digest.sha256` is the full SHA-256 of exact
  `MANIFEST.jcs.json` bytes.
- P3 `predicateType`: exactly `https://slsa.dev/provenance/v1`.
- Envelope: DSSE/Sigstore bundle version frozen before registration.
- Required standard-predicate policy: exact default GitHub build type,
  workflow/builder, source dependency, repository/ref, and full revision.
- Required authenticated-manifest policy: clean-source assertion, Git tree,
  exact opaque source-snapshot bytes, dependency lock, and execution-image
  digest. Tree-to-tar equivalence is outside this profile.

Signing the manifest subject and hashing every payload are both mandatory in P3.
Neither substitutes for the other.

## 6. Production identity profile

Preferred publication profile:

- canonical public repository `https://github.com/Ganador1/amy`;
- public GitHub Actions keyless identity;
- workflow and action dependencies pinned to immutable revisions;
- exact repository, workflow path, ref/tag rule, issuer, predicate type, and
  subject digest enforced by the verifier;
- Sigstore/GitHub verification bundle archived with public transparency evidence;
- no reusable plaintext private key in CI or the release.

The draft toolchain and exact upstream revisions are recorded in
`PRODUCTION_SIGSTORE_GATE_DRAFT.md` and
`GITHUB_ATTESTATION_POLICY_TEMPLATE_V2.json`. The release-specific source/ref,
certificate identity, trusted-root digest, and material values remain
`TBD-BEFORE-REGISTRATION`. No confirmatory P2/P3 claim is allowed until the
instantiated policy and a real A.M.Y P3 run exist as versioned bytes.

The v1 policy, result schema, CLI, cryptographic core, and genuine GitHub-CLI P2
smoke are retained at their original SHA-256 values. They are historical
evidence and are not rewritten or relabeled as v2. The current v2 line adds:

- a Draft 2020-12 closed schema for the policy document;
- a distinct template state that cannot reach cryptographic or payload checks;
- mandatory comparison of exact policy bytes to an expected SHA-256 supplied
  from outside the policy, ultimately the frozen R0 identity record;
- policy-to-policy-schema and policy-to-result-schema SHA-256 binding;
- immutable raw policy, policy-schema, and result-schema snapshots that are
  reparsed, rehashed, and revalidated at every library verification call, with
  library `ACCEPT` serialization checked against the exact result schema;
- policy, policy-schema, and result-schema SHA-256 fields in every structured
  `ACCEPT`, `REJECT`, or `ERROR` result;
- suppression of structured stdout whenever that complete output contract
  cannot first be established.

Printing the observed policy SHA after verification is not by itself policy
authorization. The verifier must compare it to an expected value obtained from
the immutable R0/deposit channel before using the policy. Likewise, a signature
authenticates the exact manifest subject under the authorized policy; it does
not make the policy, its trust root, or its delivery channel self-authenticating.

Pinned-source inspection found that default `actions/attest` provenance does
not contain A.M.Y-specific clean-state/material fields. Before confirmatory
outcomes, the project selected standard provenance plus authenticated manifest
metadata from the four reviewed profiles. The production adapter now refuses to
label attestation-only verification P3 and requires P1 payload validation for
P3. The profile remains unfrozen until S1 migration, real A.M.Y positive and
negative controls, and independent review are complete. A later profile change
would require a new protocol lineage.

Fallback protected-key signing requires an encrypted hardware/KMS-backed key and
an independently archived public trust root, but it is not interchangeable with
the public-keyless profile. Changing profile requires protocol revision before
registration.

## 7. Trust policy checks

Cryptographic signature success is necessary but not sufficient. P2/P3 also
confirm:

- approved envelope/digest/signature algorithms;
- expected issuer and trust root;
- expected repository and workflow/ref identity;
- certificate validity at evidenced signing time;
- required public transparency/timestamp evidence;
- exact authenticated manifest subject;
- revocation/compromise policy.

A key fingerprint shipped only inside the same untrusted package is not an
external trust root. HMAC is excluded from public verification because sharing
the symmetric verification secret also grants signing power.

## 8. Verification order

### Common preflight

1. Enforce file count, byte size, nesting, and processing limits.
2. Confirm required top-level inputs without following symlinks.

### P0

3. Parse the manifest under the frozen bounded ordinary JSON parser.

### P1

3. Strictly parse JSON with duplicate-key detection.
4. Verify JCS and schema.
5. Validate normalized paths, regular-file type, roles, and closed-world
   inventory.
6. Stream and compare payload byte sizes and full SHA-256.

### P2

3. Strictly parse only the bounded outer bundle and DSSE envelope needed for
   cryptographic verification; do not parse or trust the Statement payload yet.
4. Enforce approved algorithms and verify signature cryptography.
5. Verify transparency/timestamp evidence and signer/workflow policy.
6. Decode and strictly parse the now-authenticated Statement, require the frozen
   in-toto `_type`, and compare its subject to the raw exact manifest-byte
   SHA-256.
7. Do not trust or inspect referenced payloads.

### P3

3–6. Perform P2.
7. Enforce the authenticated standard predicate's type, workflow, builder, and
   resolved source dependency.
8. Enforce source/clean/tree/snapshot/lock/image policy inside the authenticated
   manifest and cross-bind the snapshot/lock to payload entries.
9. Perform P1 over the same authenticated manifest and current payload bytes;
   reject if the manifest changes before or during P1.

The common preflight bounds total entries and declared file sizes before any
cryptographic or payload operation. P3 intentionally authenticates the bounded
manifest subject before streaming all payload hashes; hashing arbitrarily large
unauthenticated payloads first would itself amplify denial-of-service cost.

An expected invalid package returns `REJECT`. Parser crashes, timeouts, or
uncaught exceptions return `ERROR` and never count as successful rejection.

## 9. Release sequence

1. Freeze protocol/profile inputs and build from a clean source revision.
2. Generate all payloads and analyses.
3. Generate final JCS manifest as the penultimate payload-description step.
4. Independently verify manifest schema, inventory, sizes, and payload SHA-256.
5. Produce the in-toto/SLSA Statement and public signature bundle as the final
   identity/provenance step.
6. Verify P3 from scratch under the exact archived trust policy, passing its
   expected SHA-256 from the independently identified R0 record.
7. Build the deterministic transport archive and compute its SHA-256.
8. Reproduce in clean CI.
9. Deposit exact verified bytes and record version DOI, archive digest, source
   identity, workflow identity, and attestation bundle.

An annotated signed Git release tag is an additional source control, not a
substitute for artifact verification or attestation.

When available, enable GitHub immutable releases before publication, create a
draft, attach every final asset, and then publish. This locks future changes to
the release tag/assets and adds a release attestation, but does not replace the
scientific manifest gate or a version DOI. Upload a deterministic source archive
as an explicit asset because GitHub's generated source ZIP/TAR downloads are not
verifiable as release assets by `gh release verify-asset`.

Zenodo is treated as a persistent versioned deposit, not asserted to be
cryptographically immutable: its current policy permits some published-file
corrections without changing the DOI. This project voluntarily forbids that
exception. Any changed bytes require a new version, new manifest, new
attestation, and new version-specific DOI.

## 10. Key handling

- Existing Atlas Ed25519 material is development-only and cannot establish the
  publication identity.
- Do not delete or rotate user keys without explicit owner approval.
- New private keys must be encrypted or hardware/KMS protected and never enter
  Git, logs, fixtures, or release archives.
- Test keys are generated solely for isolated fixtures, labeled non-production,
  and rejected by production trust policy.
- Archive public trust material and publish creation, rotation, compromise,
  revocation, and retirement records.

## 11. Rollback and model drift

- A valid signature does not make an old release current.
- Consumers select a version-specific DOI/digest. Stateful minimum-version
  enforcement is a separate optional profile requiring independently trusted
  state and is outside the primary benchmark.
- For provider-opaque models, record exact model label, Ollama client/server
  versions, parameters, timestamps, and request/response bytes. Do not claim
  hashes of inaccessible weights or bitwise replay of hidden serving state.
