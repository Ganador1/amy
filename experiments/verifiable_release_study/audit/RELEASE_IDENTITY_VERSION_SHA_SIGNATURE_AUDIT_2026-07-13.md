# Release identity, version, SHA-256, and signature audit

Prepared: 2026-07-13  
Classification: pre-registration design and present-byte audit  
Decision: **NO-GO; identity contract added, no A.M.Y production release proven**

## Scope and evidence boundary

This audit asks what an A.M.Y/Atlas/AXIOM version means when beta software
changes frequently, what exact bytes SHA-256 identifies, what the observed
signatures actually authenticate, and what must be frozen before a scientific
paper can cite a release as independently checkable.

The conclusions are grounded in current source and machine records, not in
project documentation alone:

- A.M.Y raw audit SHA-256:
  `4b3cfb9470d5f64bc4229de45f3b1e626d066a7be3d2cba014ba4d65146a63ed`;
- Atlas raw audit SHA-256:
  `949e1a5fb40fd85cc0267073d0b40eaa0832282f61ea481010e69a5f27abd8a7`;
- AXIOM raw audit SHA-256:
  `6cf3f6911bcc267a00b40d611f0023a639571d7b8620cb73719d12b9c539f2ea`;
- historical A.M.Y system-paper raw audit SHA-256:
  `36a1a81c780c6f7436b5fd80fd25eb9876ab8703dbcfa722aa50e858a5e09f7b`;
- current selected-profile raw audit SHA-256:
  `2bd43c22f3b00b26a13a68d63f38e93d129b8ce2c2371ca5930fe6a58ff6de8c`;
- current selected-profile replay-validation SHA-256:
  `e2ddd5b961ad1381d26a45d6dbf67e13a354aa20baafc0486a921b79c933a20d`.

The audit does not treat a checksum, signature, Git tag, DOI, model label, or
successful workflow as proof that a scientific statement is true. It does not
perform a new Sigstore operation, contact a provider, create confirmatory
evidence, or independently reproduce a release.

## Core conclusion

No single string such as `v1.0.0`, `4.1.0`, `beta`, `latest`, a Git commit, or a
SHA-256 is an adequate scientific execution identity.

A version label communicates a compatibility/release claim. A Git object ID
identifies a Git object under an explicit object format. A SHA-256 identifies
exact named bytes under the hash assumption. A signature authenticates a
subject under an identity/trust policy. A DOI identifies a deposited version.
These are complementary statements, not interchangeable names for the same
property.

The machine contract now requires every frozen R0/R1/R2 stage to carry an exact
18-field identity tuple: stage and stage version; repository; Git object format,
commit, and tree; exported source, dependency lock, and execution image;
payload manifest; attestation policy and trusted root; attestation bundle;
verifier binary and result schema; transport archive; version DOI; and
publication time. The contract is internally valid but currently contains no
frozen tuple.

## Assurance layers

| Layer | What can be established | What does not follow |
|---|---|---|
| Human version label | Declared ordering/compatibility intent | Exact code, environment, data, or newest trusted release |
| Git object ID | A commit/tree object under the named Git hash format | Exported archive bytes, clean workspace history, or scientific truth |
| SHA-256 recomputation | Equality to exact named bytes under the hash assumption | Author identity, trusted time, completeness, freshness, or correctness |
| Digital signature | Signed subject was accepted under cryptography and a key/certificate path | Signer authorization unless identity policy is checked; payload truth or completeness |
| Sigstore/GitHub identity policy | Certificate, workflow, repository/ref/commit, timestamp/transparency, and subject satisfy the frozen policy | Honest workflow behavior or correct workflow-authored claims |
| P1 payload verification | Closed manifest, paths, sizes, and every current payload digest pass | Authenticated publisher identity |
| Integrated P3 | Sigstore/GitHub policy plus authenticated provenance/manifest assertions plus P1 all pass | Scientific validity, complete data collection, uncompromised authorized builder, or hidden-model reproducibility |
| Independent reproduction | A separate qualified execution obtains the frozen result under declared rules | Universal correctness or representativeness of a finite attack catalog |

This separation follows the project ledger's bounded readings of
[FIPS 180-4](https://csrc.nist.gov/files/pubs/fips/180-4/final/docs/fips180-4.pdf),
[FIPS 186-5](https://csrc.nist.gov/pubs/fips/186-5/final),
[in-toto Statement v1](https://github.com/in-toto/attestation/blob/main/spec/v1/statement.md),
[SLSA artifact verification](https://slsa.dev/spec/v1.2/verifying-artifacts),
and [GitHub artifact attestations](https://docs.github.com/en/actions/concepts/security/artifact-attestations).

## Present evidence by subsystem

### A.M.Y

The current A.M.Y raw audit classifies its provenance/checksum/publication
records as unauthenticated. One audited checksum release manifest had 24/24
current digest matches, but no signature or attestation. That supports current
byte consistency relative to the stored list, not publisher identity or a
historical timestamp.

The historical formal system-paper commit had 1,148/1,148 manifest matches. Its
current working revision had 13 mismatches. Neither state had a signature,
Sigstore bundle, authenticated tag, signed release commit, or version DOI. The
committed state can therefore be described as internally digest-consistent, not
as an authenticated immutable release.

### Atlas

Atlas contains real Ed25519 verification code. All three retained manifest
signatures verified under one locally available public key, while only two of
the three referenced model artifacts matched their declared SHA-256. Zero of
three declared Git revisions resolved, and zero of three self-hashes matched
either reproduced validator algorithm.

The result is a concrete counterexample to “valid signature means valid
artifact”: the signed manifest can remain cryptographically valid while a
referenced file differs. Authorization is also unestablished because the public
key is only locally anchored. The development private key exists at
`atlas/keys/private/ed25519_private.key`, is ignored by Git, and was
group/other-readable with mode `0644` at audit time. Its bytes were deliberately
not recorded. That key must not become the publication identity.

Nine publication directories contained a stored package hash; zero fresh
reproductions matched it, zero integrity proofs repeated it, and eight proofs
asserted `blockchain_validation=true`. The local hash-chain code and labels do
not establish distributed consensus, external timestamping, or independent
validation.

### AXIOM

The current source boundary identifies AXIOM as a package/project and class/demo
label over Atlas app code, not a separate top-level Python package or route
surface. The package metadata calls `axiom-atlas` version `4.1.0` alpha, while
application endpoints also expose A.M.Y labels and versions. Those labels are
not a coherent execution identity.

Among 11 classified scientific/claim artifacts, zero contained authentication,
content-digest, source-revision, dependency-identity, immutable-model-identity,
seed, provenance, or raw-exchange fields. Two reports recorded zero queries,
zero successful connections, and zero analyzed objects while repeating four
positive findings. Those artifacts cannot be upgraded into measured scientific
evidence by hashing them after the fact.

### New selected release study

The selected adapter has a materially stronger design:

- the exact manifest bytes are the sole required subject;
- the external `gh` verifier binary is SHA-256 pinned and copied before use;
- tokens/configuration are isolated;
- exact certificate identity, issuer, repository, workflow/source commits, ref,
  hosted-runner status, predicate, and transparency witness are checked;
- P3 checks the default SLSA workflow/builder/source dependency and the
  explicitly labeled workflow-authored source/clean/tree/snapshot/lock/image
  assertions;
- P3 then executes all six P1 checks over current payload bytes and rejects a
  changed manifest.

The only retained real Sigstore result is P2 interoperability for the official
GitHub CLI release. It is not A.M.Y and does not exercise integrated P3. The
selected 24 clean rows and 164 development evaluations use controlled public
test PKI and are explicitly non-production.

## Frequent beta releases: required rule

[Semantic Versioning](https://semver.org/) permits major version zero for
initial development, but a version remains a compatibility label, not a byte
identity. Existing A.M.Y history already includes `v1.0.0`; the same
distribution must not pretend that a later experimental line precedes it by
publishing `0.y.z`. Use a later prerelease such as `2.0.0-alpha.1`, or use a
genuinely distinct distribution identity whose version history begins at
`0.1.0`.

Every run, including a development build, must record:

1. distribution identity and declared version;
2. Git object format plus full commit and tree OIDs;
3. dirty state and, for exploratory dirty work only, a retained patch/content
   snapshot;
4. SHA-256 of deterministic exported source bytes;
5. dependency lock and execution-image digest;
6. command, config, seeds, locale, timezone, and observable tool/model versions;
7. exact inputs and outputs or their closed-manifest SHA-256 bindings.

“Latest” may be a user-interface pointer but is forbidden in a scientific
execution identity. A valid old signature remains valid. Detecting rollback or
enforcing a minimum version requires separately trusted state; SHA-256 and
Sigstore do not make freshness stateless.

Git SHA-1 object IDs in the current repository must be labeled as Git SHA-1
OIDs. They must not be padded, transformed, or called artifact SHA-256. The
separate exported-source SHA-256 identifies a different byte object, consistent
with the [Git SHA-256 transition model](https://git-scm.com/docs/hash-function-transition/2.49.0.html).

## R0 → R1 → R2 lineage

The new contract prevents one mutable tag from standing for the whole study:

- **R0** freezes protocol, bases, catalog, compatibility decisions, generator,
  oracle, analysis, policy, environment, and independent reviews before any
  confirmatory generation.
- **R1** is created after registration by exact R0 bytes. It contains every
  generation attempt, case archive, raw result, log, failure, and deviation and
  cites R0 by external record SHA-256, manifest/archive SHA-256, and version DOI.
- **R2** contains analyses, figures, claim ledger, manuscript source/render, and
  publication material and cites exact R0 and R1 parent records.

The record deliberately contains no self-hash. Its exact raw SHA-256 is carried
by deposit metadata and by the next stage. A correction never changes old
bytes: it creates a new manifest, attestation, archive, version, and
version-specific DOI. A concept DOI can group versions but cannot identify the
bytes used by an analysis. [Zenodo assigns version and concept DOIs](https://zenodo.org/help/versioning)
but permits limited file corrections, so this project's no-replacement rule is
stricter than repository behavior. GitHub immutable releases can lock future
release tags/assets, but they do not replace the scientific manifest, DOI, or
independent reproduction.

Machine records:

- contract SHA-256:
  `6022fe99d4d577a31d86bae69484a314aa84dce11a1bc7b2769e4b8a8ff82ae0`;
- retained validation SHA-256:
  `7f9b714908087356fb02522d5c4076a19d55893d9ee32553ac3c6c9bcb3cf5a1`;
- contract schema SHA-256:
  `00289ce30246d0c7b9c3574262149a77e478424103fcaeb3fc80e393cabcbcf8`;
- validation schema SHA-256:
  `531ff7fd58c37400a9ff35ebae3db7d64135e5dde75d6b19a3f18fd50e4d30c8`;
- validator SHA-256:
  `904f90d289dc1e403e24758a008238cb463f7a832791f580d688ede3da3db294`.

The retained validator reports `valid=true` only for internal contract
consistency. It separately reports `release_freeze_permitted=false`, R0 draft,
R1/R2 absent, 12 unresolved pointers, and all A.M.Y/Atlas/AXIOM identities
unresolved. It reads no verifier results or confirmatory artifacts, uses no
network, and performs no independent review.

## Signature and policy findings

Cryptographic verification is necessary but remains insufficient in five
distinct ways:

1. the signed subject must equal the exact intended manifest bytes;
2. the certificate/key must satisfy an externally trusted identity policy;
3. required timestamp/transparency evidence and trusted-root lifecycle must be
   established independently of the package;
4. provenance fields must satisfy a frozen policy, while workflow-authored
   claims remain labeled as such;
5. every referenced payload byte must be checked separately, and scientific
   truth/review must remain outside the cryptographic claim.

The historical production v1 CLI correctly attaches SHA-256 of the exact raw policy bytes to
every result after strict policy parsing, and the production result schema
requires `policy_sha256` for `ACCEPT`. Its template SHA-256 is
`68ea605c25a8e73ebe955a1bfd3977a309f13b40b9a112aee6b2e9bc5cd38c26`;
the result-schema SHA-256 is
`64eef1a87da45dff355047963ebe762dfced1a2ba7e60be9a87dfcc28a1e2c18`.

Two residual contract issues should be closed by a versioned migration, not by
silently editing the present v1 output contract:

- the GitHub attestation policy document itself has no closed JSON Schema; the
  adapter checks required used fields and cross-field invariants, but unknown or
  purely documentary fields can be ignored;
- the Python evidence dataclass and `evidence_to_json` do not themselves carry
  `policy_sha256`; the normative CLI adds it before schema validation. A library
  caller can therefore obtain a non-publishable evidence object unless it uses
  the CLI's finalization path.

A v2 migration should introduce a schema-closed policy document, bind the exact
policy-schema digest, represent a loaded policy through immutable raw bytes,
carry policy and policy-schema hashes inside library evidence, and keep the
historical v1 schema and upstream smoke byte-identical.

### Post-audit v2 remediation implemented in this draft

That migration now exists as a separate, non-destructive v2 line. The current
exact identities are:

- policy template:
  `0d24ac7288782b3d8ca681bc6a986ad421e13be5480b10bffe3ad0b2433b45cf`;
- policy schema:
  `d7bbbfa9045dceb6c63244d627396c380bf76a7a7cdaa5883fad6411ff19510a`;
- terminal-result schema:
  `fca95c09b26590c8ca84346c72627b07bf4de967cc4135d585eab6f825ebdaa4`;
- v2 library wrapper:
  `8e0286e3c933452f14b2f7e7ebde5324db93026c17cfb8509cb3075159f20bf8`;
- v2 CLI:
  `755b1f222e46655b4e2b7bbf15d435395e0409d3f1af6dbf8d5f270058642999`.

The v2 loader requires an expected policy SHA-256 supplied outside the policy,
compares it before policy use, validates the policy against the exact schema
whose digest the policy carries, and rematerializes/revalidates immutable raw
policy, policy-schema, and result-schema bytes for every verification call. A
plain policy dictionary is not accepted. Library `ACCEPT` serialization is
validated against those exact result-schema bytes; every structured `ACCEPT`,
`REJECT`, or `ERROR` carries all three SHA-256 values. The CLI emits no JSON when
it cannot first establish that complete contract.

Twenty-one adversarial/regression tests cover wrong external policy digest,
duplicate policy and policy-schema keys, unknown fields, policy-schema mismatch,
frozen cross-field inconsistency, template misuse,
plain-dictionary bypass, post-load byte changes, evidence snapshotting,
result-schema substitution, library-side output-schema enforcement,
unbound-output suppression, and the exact v1 invariants. The five historical
v1 artifacts listed above remain byte-identical. This closes the identified
code and contract gap; it does **not** freeze the v2 template, create its
external R0 authorization, exercise a real A.M.Y P3 release, or supply
independent review.

## Version-transition decision table

| Change | Required action |
|---|---|
| Draft code/policy changes before R0 and before confirmatory access | New draft bytes and hashes; rerun design validation; never call prior hashes current |
| Public beta package behavior changes | Increment the declared prerelease/version and record a new exact execution tuple |
| Any R0-affecting fix after registration but before R1 | New R0 registration lineage; old R0 remains available |
| Generator/verifier/oracle/analysis fix after any confirmatory attempt | Preserve failed lineage and create a new registration plus new R1; never patch outcomes in place |
| New evidence generated by unchanged exact R0 | New R1 version linked to the same exact R0, with all attempts/deviations retained |
| Paper-only correction that cannot affect evidence | New R2/correction linked to unchanged R0/R1; old R2 remains available |
| Trust-root, key, workflow, or verifier compromise | Publish compromise/revocation record, new policy/root/tool lineage, and reassess affected releases; a new signature must not overwrite history |
| Provider-opaque model alias changes or is suspected to drift | Treat each exchange as a new observation; retain request/response bytes and observable metadata; do not invent a weight hash |

## Blocking findings before any production or paper claim

1. Fourteen release-specific policy strings remain unresolved.
2. The required release workflow does not exist, and current workflows using
   mutable major tags are not approved as the scientific builder.
3. No clean externally identified R0 snapshot, registry identifier, or version
   DOI exists.
4. A.M.Y, Atlas, and AXIOM component identities are not frozen in the lineage
   contract.
5. No real A.M.Y P3 positive result or mandatory production negative-control
   set exists.
6. Trusted-root bootstrap, lifecycle, and independent digest recording are not
   complete.
7. The v2 hardening is implemented and same-environment tested, but its template
   remains release-uninstantiated, externally unauthorized by R0, unexercised on
   a real A.M.Y P3 release, and not independently reviewed.
8. Fifty-four selected compatibility rows and eighteen base hashes remain
   unresolved.
9. Oracle/proposition review by a qualified non-implementer is absent.
10. The six-base post-registration case runner, R1 evidence release, external
    reproduction, and R2 paper release do not exist.

## Permitted wording now

> The pre-registration design now specifies a hash-bound version and release
> lineage that distinguishes software labels, Git objects, exact artifact
> bytes, trust policy, attestation, and publication identity; the contract is
> internally consistent but no frozen or production A.M.Y release has yet been
> established.

The words “100% verifiable,” “production-ready,” “cryptographically proven
science,” “blockchain validated,” and “independently reproduced” remain
prohibited for the current state.
