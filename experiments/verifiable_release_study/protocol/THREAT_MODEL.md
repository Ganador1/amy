# Threat Model

Version: `0.3.0-draft`  
Scope: release artifacts and their verification, not scientific truth in general

## Assets

- exact bytes of raw data, code, configurations, prompts, responses, analyses,
  figures, manuscripts, manifests, and transport archives;
- binding between manifest bytes and every listed payload;
- binding between authenticated manifest bytes and source/build provenance;
- identity and authorization of the release workflow;
- exact trust-policy, policy-schema, and result-schema bytes plus their external
  R0 authorization;
- public evidence needed for later/offline verification;
- confidentiality and control of any signing credential;
- unambiguous version identity of each identified deposit, with later
  corrections represented by new append-only records rather than silent
  replacement;
- availability, treated separately from integrity and authentication.

## Trust boundaries

1. Dirty research workspace → clean release build.
2. Source repository → pinned CI workflow/builder.
3. Builder → in-toto/SLSA Statement and signature service.
4. Signature service → transparency log and archived verification bundle.
5. Manifest producer → payload store.
6. Release publisher/archive → independent verifier.
7. Ollama client → Ollama server → opaque cloud provider.
8. Authors/automation → independent oracle reviewer and reproducer.
9. Cryptographically identified R0/deposit record → verifier operator/CLI
   expected-policy input.

## Adversary classes

| ID | Capability | Profiles expected to provide the relevant check |
|---|---|---|
| A0 | Accidental payload corruption or truncation | P1, P3 |
| A1 | Can modify payload bytes but not authenticated manifest bytes | P1, P3; P2 deliberately cannot |
| A2 | Can replace payload and unauthenticated manifest coherently | P2, P3; P1 deliberately cannot authenticate |
| A3 | Has a cryptographically valid but unauthorized signing identity | P2, P3 pinned identity policy |
| A4 | Can replay an authorized attestation for a different manifest | P2, P3 subject binding |
| A5 | Can create unsafe paths, omissions, extras, or malformed manifests | P1, P3 structural/content policy |
| A6 | Can alter the standard source dependency or workflow-authored source/dirty/tree/snapshot/lock/image metadata while still producing an authenticated release | P3 standard-provenance plus authenticated-manifest policy |
| A7 | Can remove required transparency evidence | P2, P3 under the frozen public-keyless profile |
| A8 | Can trigger oversized input, parser ambiguity, symlink escape, or resource exhaustion | All profiles' preflight limits; P1/P3 structural policy |
| A9 | Controls the authorized builder/signing identity | Outside cryptography-only protection; requires operational controls and independent review |
| A10 | Is an authorized dishonest author | Cannot be made scientifically truthful by a signature |
| A11 | Controls the archive host but not the authorized signer | Replacement is detectable; deletion remains an availability problem |
| A12 | Controls an opaque cloud-model backend | Released exchange bytes are checkable; hidden provider state is not reconstructible |
| A13 | Can substitute policy/schema files delivered beside an otherwise valid bundle but cannot alter the externally identified R0 record | V2 external expected-policy SHA plus policy-bound schema digests |

## Target properties

- **Bounded input:** untrusted files are processed under frozen size/count/depth
  limits, with `REJECT` for policy-invalid input rather than crashes.
- **Manifest structure:** JCS, schema, duplicate-key, path, file-type, link-count,
  role, and inventory rules are deterministic and fail closed.
- **Payload integrity:** every listed regular file is streamed and checked by
  exact byte size and full SHA-256.
- **Manifest authenticity:** a verified Statement subject equals the SHA-256 of
  exact manifest bytes.
- **Identity authorization:** the cryptographic signer, repository, workflow,
  and ref match a trust policy archived outside the package.
- **Policy authorization:** exact raw policy bytes match the expected SHA-256
  obtained from the immutable R0/deposit channel before the policy is used; that
  policy binds its exact policy and terminal-result schemas.
- **Provenance conformance:** standard predicate type, workflow, builder, and
  source dependency match policy; separately labeled workflow-authored
  source/clean/tree/material assertions in the authenticated manifest match
  policy and their cross-bound payload entries.
- **Auditability:** every terminal decision has a stable reason code and retained
  evidence.
- **Reproduction:** a separate clean environment obtains the declared result or
  decision within the frozen tolerance. This is tested, not inferred.

## Central abuse paths

### Stored digest without recomputation

The record contains a SHA-256 string but the verifier checks only file existence
or hash syntax. A changed payload can still report “valid.” P0 models this class;
P1/P3 must hash the current payload bytes.

### Signature-only false positive

The signature over manifest bytes is valid but referenced payloads are missing or
different. P2 intentionally accepts this class because it authenticates only the
manifest subject. P3 must independently apply all P1 checks.

### Coherent manifest substitution

An attacker replaces a payload and recomputes an unsigned manifest. P1 sees an
internally consistent package and accepts. P2/P3 must reject because the exact new
manifest digest lacks the authorized subject binding.

### Authorized signature, wrong identity policy

Signature mathematics succeeds under a certificate/key that is not authorized
for the release workflow/ref. P2/P3 must separate `SIGNATURE_INVALID` from
`SIGNER_UNAUTHORIZED` or `BUILDER_UNAUTHORIZED`.

### Coherent policy and schema substitution

An attacker supplies a weaker policy, a matching permissive schema, and a valid
bundle, then reports the newly computed policy digest. Merely printing that
observed digest does not authorize the policy. V2 requires an expected policy
SHA-256 from the independently identified R0 record before policy use; the
authorized policy then binds the exact policy-schema and result-schema bytes.
If this chain cannot be established, the CLI emits no structured decision.

### Predicate or source confusion

An authenticated Statement names the right manifest but carries an unsupported
predicate, wrong source revision, dirty build, or wrong material. P2 accepts by
design because it enforces no predicate semantics; P3 rejects under provenance
policy.

### Circular/ambiguous manifest hashing

A manifest stores a digest over itself, or producer/verifier hash different JSON
serializations. Control: the manifest has no self-hash; JCS produces deterministic
bytes; an external authenticated Statement subjects those exact bytes.

### Omission and unexpected input

An attacker removes a required payload and its entry or adds an unlisted file
consumed downstream. P1/P3 enforce required roles and a closed-world inventory.

### Path, link, and non-regular-file escape

An entry uses an absolute/parent path, duplicate normalized spelling, Unicode or
platform ambiguity, a symbolic link, a multiply linked inode, or a non-regular
file. P1/P3 permit only frozen portable relative paths and singly linked regular
files below the root. Verification uses a private case snapshot, non-following
metadata inspection/opening, and pre/post-read metadata comparison; residual
filesystem-race claims remain bounded by B14.

### Parser/resource denial

An attacker supplies huge objects, deep nesting, duplicate keys, or malformed
envelopes. Each profile applies limits before unbounded allocation. Strict parsing
of untrusted bytes is allowed; no parsed claim is trusted before the required
cryptographic and policy checks succeed.

### Rollback

An old release and signature can remain valid. The primary study makes no
stateless rollback claim. A consumer must request a version-specific DOI/digest
or supply separately trusted minimum-version/checkpoint state.

### Key exposure

A plaintext private key readable by other local users can produce signatures
indistinguishable from the owner. The current Atlas development key is not an
acceptable publication identity. Production uses public keyless CI or protected
key storage with published rotation/revocation records.

### Cloud model drift

The same provider label can later route to different hidden weights or serving
code. Exact requests/responses and observable versions are retained. No claim is
made that unavailable weights can be hashed or reconstructed.

## Non-goals

- proving truth, novelty, or honest authorship cryptographically;
- protection after complete compromise of the authorized builder and all policy
  inputs;
- archive availability or confidentiality;
- hidden model-weight reproducibility;
- replay protection without trusted freshness state;
- describing a local hash chain as distributed consensus;
- proving ownership behind a self-generated key without an external identity
  policy;
- claiming coverage beyond the frozen released catalog.
