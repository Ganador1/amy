# From Checksums to Attestations: Evaluating Tamper-Evident Scientific Releases Under Software and Model Drift

<!-- MANUSCRIPT-STATUS: SKELETON -->
<!-- protocol_version: 0.3.0-draft -->
<!-- skeleton_prepared: 2026-07-13 -->
<!-- skeleton_validated: 2026-07-14 -->
<!-- Sections permitted at this stage: Introduction, Background, Threat Model,
     Verification Profiles, Study Design, Exploratory Case Study (structure only),
     Limitations, Availability.
     Sections FORBIDDEN until the stated gate: Abstract (R1 + final audit),
     Results (R1), Discussion (R1), Conclusion (R1 + external reproduction),
     any numerical outcome. Exact abstract and conclusion wording must be
     present in evidence/CLAIM_EVIDENCE_MATRIX.csv. -->
<!-- Every substantive paragraph must carry a visible draft evidence label:
     OBSERVED | REPRODUCED | SPECIFIED | TESTED | INFERRED | EXTERNAL | UNKNOWN
     (see protocol/CLAIM_BOUNDARIES.md). Before R2, every manuscript claim must
     also receive a claim-ledger entry. Unlabeled prose is unfinished, not
     implicitly OBSERVED. -->

## Abstract

<!-- FORBIDDEN-UNTIL-R1-AND-FINAL-AUDIT: The abstract may contain only claims
whose exact wording appears in evidence/CLAIM_EVIDENCE_MATRIX.csv with an
allowed_now=yes status after the independent final audit. Do not draft
placeholder abstract prose: placeholder abstracts anchor conclusions. -->

`[ABSTRACT-FORBIDDEN-UNTIL-R1]`

## 1. Introduction

Software pipelines produce, transform, and package scientific data, code,
figures, and manuscripts. Published autonomous-agent frameworks now also
describe systems that generate ideas, execute code, produce figures and draft
papers. [S58] [EXTERNAL]

When a reader downloads a release of such work, one practical question is
logically prior to judging the science: **are these the bytes identified by the
release record, were they associated with the claimed workflow under the stated
policy, and is every referenced artifact present and unchanged relative to its
expected digest?** [SPECIFIED]

Standards expose mechanisms with different scopes: message digests identify
byte changes relative to expected digests; digital signatures authenticate
specified signed material under a trust model; and in-toto/SLSA statements can
represent subjects, builders, source dependencies, and build parameters.
[S01] [S02] [S03] [S10] [S11] [EXTERNAL]

This draft decomposes release verification into four profiles intended for R0
freeze—existence/self-report (P0), content checksums (P1), signature
authentication of a manifest subject (P2), and an integrated attested release
combining content, authentication, and provenance policy (P3). Confirmatory
evaluation against the machine-readable corpus is forbidden until the design
is independently reviewed, frozen, and preregistered. [SPECIFIED]

Two questions are kept deliberately separate throughout: [SPECIFIED]

1. **Implementation conformance.** Does each verifier implement its R0-frozen
   profile correctly on every structurally applicable case?
2. **Target acceptance coverage.** Which packages that violate the study's
   R0-frozen target release contract are nevertheless accepted by each partial
   profile after confirmatory execution?

The distinction matters because a partial profile accepting an invalid package
is often *correct implementation behavior* and simultaneously a miss relative
to the stronger target contract. Reporting the two as one number is a category
error this design forbids. [SPECIFIED]

### 1.1 Intended contributions

<!-- Derived from protocol/PROTOCOL_DRAFT.md §2. Contribution wording is
SPECIFIED until R1 evidence exists; the final paper must restate each as
OBSERVED/TESTED with artifact links or delete it. -->

The following are design objectives, not completed contributions. Each must be
restated with post-R1 evidence or removed from the final manuscript.
[SPECIFIED]

1. A precise decomposition of existence checks, payload checksums, signature
   authentication, and provenance-policy verification, with a
   machine-readable capability and limitation matrix. [SPECIFIED]
2. An R0-frozen, machine-readable adversarial corpus of release mutations with
   exact changed bytes, structural applicability, expected decisions, and
   stable reason codes. [SPECIFIED]
3. A fail-closed reference verifier for an attested scientific release,
   including bounded input handling and closed-world inventory checking.
   [SPECIFIED]
4. A code-and-artifact-grounded case study of A.M.Y, Atlas, and AXIOM, reported
   as exploratory evidence including working controls and negative findings.
   [SPECIFIED]
5. An artifact package that an external team can exercise from case
   generation to paper tables and figures. [SPECIFIED]

This work does not propose a new cryptographic primitive. It composes published
digest, envelope, attestation, transparency, and provenance mechanisms.
[S01] [S10] [S11] [S25] [S27] [EXTERNAL]

### 1.2 What this paper does not claim

A valid signature does not by itself demonstrate that a signer is authorized,
that the signed subject is the intended artifact, that referenced payloads were
recomputed, or that the scientific content is true. Those require distinct
policy and content checks. [S02] [S03] [S13] [S16] [EXTERNAL]

The study therefore reports each link separately, and its future coverage
claims are bounded by the catalog frozen at R0: a complete-coverage statement
will mean every compatible case in that released catalog version, never an
unobserved attack population. [SPECIFIED]

## 2. Background and Related Work

### 2.1 Integrity and signing standards

FIPS 180-4 specifies SHA-256 as a message-digest algorithm, while NIST's
signature material distinguishes detection of modification and signatory
authentication from the truth of signed information. RFC 8785 addresses a
different problem: obtaining a repeatable JSON serialization suitable for
hashing or signing. None of these documents turns a newly computed digest into
an authorized expected value. [S01] [S02] [S03] [S22] [EXTERNAL]

DSSE binds a payload type and payload bytes through pre-authentication encoding
but deliberately does not define identity trust. An in-toto Statement binds
named subjects to a predicate, and SLSA Build Provenance defines fields for the
builder, build definition, invocation parameters, dependencies, and run
details. A Sigstore bundle carries signed content together with verification
material; acceptance still depends on a verifier's identity, trust-root, and
policy inputs. [S10] [S11] [S15] [S25] [S27] [EXTERNAL]

The Update Framework addresses software-update concerns such as rollback,
freeze, mix-and-match, and wrong-file attacks through trusted role metadata,
versions, expiration, and retained client state. This study does not implement
TUF and therefore makes no stateless freshness claim; TUF is used only to make
that boundary explicit. [S54] [EXTERNAL]

### 2.2 Software supply-chain security

SLSA treats provenance verification as a combination of artifact identity and
policy over provenance, not signature mathematics alone. GitHub artifact
attestations instantiate signed provenance for workflow-produced artifacts,
while GitHub explicitly warns that an attestation does not guarantee that an
artifact is safe or free of vulnerabilities. The selected `actions/attest`
release also distinguishes default SLSA provenance generation from custom
workflow-supplied predicates. [S12] [S13] [S16] [S28] [S37] [EXTERNAL]

Reproducible Builds defines a reproducible build as one where the same source,
build environment, and instructions let another party recreate bit-for-bit
identical specified artifacts. That definition is narrower than scientific
replication and stronger than merely obtaining the same parsed result. This
study accordingly reports archive-byte reproduction, verifier-decision
reproduction, and scientific-tolerance reproduction as different outcomes.
[S55] [EXTERNAL]

### 2.3 Reproducibility and preregistration in computational science

The National Academies' consensus report distinguishes computational
reproducibility using the same data and computational methods from replication
that obtains new data. OSF registrations provide time-stamped, read-only study
records, while the Registered Reports format places peer review of questions
and methods before outcomes are known. This study is currently only a draft:
neither an OSF registration nor a Registered Report review has occurred.
[S20] [S56] [S57] [EXTERNAL]

ACM artifact review separately labels artifact availability, artifact
functionality, and independent reproduction. That separation motivates this
paper's refusal to infer external reproduction from a same-author validator or
from a cryptographic integrity check. [S21] [EXTERNAL]

### 2.4 AI-generated and AI-assisted science

Lu et al. describe an autonomous research framework that generates ideas,
writes and executes code, produces figures and papers, and applies a simulated
review process in machine-learning domains. That paper is primary evidence of
what its authors report about their system, not independent validation of every
generated scientific claim. [S58] [EXTERNAL]

The present study does not benchmark scientific creativity or model
intelligence. It treats model requests and responses as release artifacts,
declares undisclosed weights and serving state unreproducible, and treats model
reviews as advisory records rather than oracle labels or human peer review.
[SPECIFIED]

### 2.5 Positioning

This study combines a finite mutation corpus, profile-specific conformance
oracles, a stronger target release contract, exact-byte release identities, and
predeclared separation of exploratory, confirmatory, and reproduction evidence.
It applies those components to scientific-release packages rather than claiming
to replace SLSA, in-toto, Sigstore, TUF, reproducible-build tooling, or artifact
review. [SPECIFIED]

No systematic literature review has been performed. The manuscript therefore
does not claim to be the first or only benchmark with any of these individual
properties; any stronger novelty statement requires a documented search and
independent review before submission. [UNKNOWN]

## 3. Threat Model

<!-- Derived from protocol/THREAT_MODEL.md v0.3.0-draft. This section may be
edited for prose, but any semantic divergence from the frozen threat model at
R0 is a defect: the R0 bytes win. -->

### 3.1 Assets

The protected assets are: the exact bytes of data, code, configuration,
prompts and model responses, analyses, figures, manuscripts, manifests, and
transport archives; the binding between manifest bytes and every listed
payload; the binding between authenticated manifest bytes and source/build
provenance; the identity and authorization of the release workflow; the exact
trust-policy and schema bytes together with their external authorization
channel; the public evidence needed for later or offline verification; and
the unambiguous version identity of each version-specific archived deposit.
Availability is tracked as a separate property from integrity and
authentication. [SPECIFIED]

### 3.2 Trust boundaries

Nine boundaries are modeled, from the dirty research workspace through source
repository, pinned CI workflow, signature and transparency services, manifest
producer, publisher/archive, and opaque cloud-model providers, ending at the
boundary between the archived registration deposit (R0) and the verifier
operator who must supply its expected digest. [SPECIFIED]

### 3.3 Adversary classes

<!-- Table mirrors THREAT_MODEL.md; keep IDs stable. -->

| ID | Capability | Check expected from |
|---|---|---|
| A0 | Accidental payload corruption or truncation | P1, P3 |
| A1 | Modify payload bytes, not authenticated manifest bytes | P1, P3 (P2 deliberately cannot) |
| A2 | Replace payload and unauthenticated manifest coherently | P2, P3 (P1 deliberately cannot authenticate) |
| A3 | Valid but unauthorized signing identity | P2, P3 pinned identity policy |
| A4 | Replay an authorized attestation for a different manifest | P2, P3 subject binding |
| A5 | Unsafe paths, omissions, extras, malformed manifests | P1, P3 structural policy |
| A6 | Alter the standard source dependency or workflow-authored source/dirty/tree/snapshot/lock/image metadata in an authenticated release | P3 provenance + authenticated-manifest policy |
| A7 | Remove required transparency evidence | P2, P3 (public keyless profile) |
| A8 | Oversized input, parser ambiguity, symlink escape, resource exhaustion | All profiles' preflight; P1/P3 structural policy |
| A9 | Controls the authorized builder/signing identity | Outside cryptographic protection (operational controls) |
| A10 | Authorized dishonest author | Cannot be made truthful by a signature |
| A11 | Controls archive host, not the authorized signer | Replacement detectable; deletion is availability |
| A12 | Controls an opaque cloud-model backend | Exchange bytes checkable; hidden state is not |
| A13 | Substitutes policy/schema files beside a valid bundle | External expected-policy digest + hash-bound schemas |

### 3.4 Central abuse paths

The design is organized around named abuse paths rather than abstract goals:
stored digests that are never recomputed; signature-only false positives;
coherent manifest substitution; authorized signatures under the wrong identity
policy; coherent policy-and-schema substitution; predicate or source
confusion; circular or ambiguous manifest hashing; omission and unexpected
input; path, link, and non-regular-file escape; parser and resource denial;
rollback; key exposure; and opaque cloud-model drift. Benchmark-covered paths
map to mutation operators or robustness checks; other paths remain explicit
non-goal boundaries. Only benchmark-covered paths enter the confirmatory
denominator. [SPECIFIED]

### 3.5 Explicit non-goals

The study does not attempt to prove truth, novelty, or honest authorship
cryptographically; does not protect against complete compromise of the
authorized builder together with all policy inputs; does not address archive
availability or confidentiality; does not claim hidden model-weight
reproducibility; does not claim replay protection without trusted freshness
state; and does not claim coverage beyond the frozen released catalog.
[SPECIFIED]

## 4. Verification Profiles

<!-- Derived from protocol/PROTOCOL_DRAFT.md §5–§6. Prose may be tightened;
semantics must match the future frozen R0. -->

### 4.1 Common release object

The benchmark input is a release directory containing an RFC 8785 (JCS)
canonical manifest listing a closed-world payload inventory with semantic
roles, byte sizes, and full SHA-256 digests; one Sigstore bundle conforming to
the R0-frozen policy whose DSSE envelope payload is an in-toto Statement
authenticating the SHA-256 of
the exact manifest bytes; and the payload files themselves. The manifest
contains no signature and no self-hash, so no file is required to hash or
sign itself. [SPECIFIED]

### 4.2 Profiles P0–P3

All profiles return `ACCEPT`, `REJECT`, or `ERROR` with one primary reason
code; `ERROR` never satisfies an expected `REJECT`. Per-check output
distinguishes `PASS`, `FAIL`, `NOT_RUN`, and `NOT_REQUIRED`, so a reader can
tell failure from deliberate omission and short-circuiting. [SPECIFIED]

- **P0-METADATA** — existence, size bound, and ordinary JSON parse of the
  manifest; reads stored status fields; validates nothing else. Intentionally
  weak and exactly specified so its oracle is not invented per case.
  [SPECIFIED]
- **P1-CHECKSUM** — canonical JCS manifest, frozen schema, duplicate-key and
  duplicate-path rejection, portable relative paths only, singly linked
  regular files only, required roles, closed-world inventory, and streamed
  recomputation of full SHA-256 and size for every payload; no
  authentication. [SPECIFIED]
- **P2-SIGNATURE_ONLY** — byte-exact trust-policy authorization against an
  externally supplied expected digest, bounded DSSE/Sigstore verification
  under frozen roots, pinned identity policy, and binding of the
  authenticated Statement subject to the SHA-256 of the raw manifest octets;
  deliberately validates no payload bytes and no provenance semantics. This
  ablation isolates authentication from artifact verification. [SPECIFIED]
- **P3-ATTESTED_RELEASE** — every P1 and P2 check, plus in-toto Statement v1
  with the SLSA provenance v1 predicate, exact workflow/builder/source
  policy, and cross-binding of workflow-authored source-snapshot,
  dependency-lock, and execution-image assertions to manifest payload
  entries. Authentication proves that the authorized workflow asserted those
  values, not that the platform independently measured their truth.
  [SPECIFIED]

### 4.3 Target release contract

The target contract is an author-defined, standards-grounded normative
acceptance policy — bounded inputs, canonical schema-valid manifest,
closed-world inventory, exact payload digests, authenticated subject,
authorized public identity with transparency evidence, and required SLSA
policy. The exact contract and oracle must be independently reviewed and frozen
before registration. Once registered, it remains a normative policy judgment,
not an empirical ground truth, and a conforming P3 is not evidence about
threats the contract excludes. [SPECIFIED]

## 5. Study Design (Draft; Not Yet Preregistered)

<!-- Derived from PROTOCOL_DRAFT.md §3–§4, §8–§15. All counts below are
DESIGN-STATE values as of protocol 0.3.0-draft and must be regenerated from
the frozen R0 bytes at registration; hand-maintained numbers are forbidden in
the final manuscript. -->

### 5.1 Layers and research questions

Four layers separate evidence classes: an exploratory baseline audit (L0), a
standards-grounded mechanism analysis (L1), a confirmatory finite benchmark
over packages to be frozen at R0 (L2), and reproduction in a clean environment plus, for
any external-reproduction claim, execution by a person not involved in
implementation (L3). Research questions RQ1–RQ5 address partial-mechanism
acceptance, per-profile implementation conformance, target-invalid acceptance
by profile and attack family, integrated-profile binding, and
cross-environment decision determinism; the A.M.Y/Atlas/AXIOM case-study question
is exploratory and reported outside the confirmatory block. [SPECIFIED]

### 5.2 Units, corpus, and compatibility

The atomic unit is one base release bundle crossed with one structurally
compatible mutation operator; four profile decisions on one unit are paired
observations, not independent units. The draft base registry specifies CC0 fixtures
of deliberately different structure (tabular data, manuscript+PDF, large
binary model, nested source trees, an opaque-model exchange fixture, and a
mixed deep-path release). Compatibility is decided only from mutation
prerequisites — never from expected outcomes — and a separate validator
recomputes the full matrix and confirms that poisoning every expectation
field leaves compatibility unchanged. Pending rows are named as pending, not
silently counted; a planned unit whose generation fails remains a retained
failure and cannot disappear as not-applicable. `[COUNTS-FROM-R0-BYTES:
bases, operators, compatible/pending/not-compatible rows, planned units]`
[SPECIFIED]

### 5.3 Oracle construction and independence

The design requires mutation generation to write no expected or observed
decision. The oracle—target decisions, per-profile expectations, and expected
reason codes—is a separate module rendered only from the R0-frozen catalog, importing no
generator, verifier, or evaluator code. Case IDs are opaque during verifier
execution and expected labels are joined only after outputs are write-locked
and hashed. Before registration, a qualified human who neither implemented
the verifier, generator, or analysis nor authored the catalog, oracle, or
propositions must review the exact SHA-bound R0 bytes without access to
confirmatory outcomes. [SPECIFIED]

### 5.4 Falsification conditions

Six draft design requirements function as falsification rules rather
than probabilistic claims: content binding (D1), authentication binding (D2),
intended complementarity of partial profiles (D3), provenance policy
enforcement (D4), clean acceptance without post-hoc relabeling (D5), and
cross-environment determinism of decision and primary reason code (D6).
Acceptance of a changed payload under an unchanged manifest falsifies P1/P3
content binding; acceptance of a changed manifest under the original valid
attestation falsifies P2/P3 subject binding; a clean-package rejection cannot
be repaired by reclassifying the case as incompatible. [SPECIFIED]

### 5.5 Execution, error, and retry rules

Expected-invalid packages must produce `REJECT`, not `ERROR`; a crash remains
in the data. The draft policy permits one execution attempt per case, with at
most one complete-environment rerun under predeclared typed infrastructure
predicates recorded before any outcome exposure. Scientific intent must be
durably persisted before any child process is spawned, and no post-intent event
may authorize a retry. Official-attempt selection must be sealed for all
environments before any result is released for decoding. A code change after any
confirmatory attempt creates a new exploratory lineage or a new
preregistration; it cannot repair the registered result in place. [SPECIFIED]

### 5.6 Analysis rules

Every manuscript number, table, and figure is generated from released
case-level data; hand-entered result numbers are forbidden. Case-level
results precede any descriptive total; implementation-conformance failures
are kept separate from target-contract misses; the catalog is treated as a
finite designed benchmark, so no p-values, confidence intervals, or pooled
"security scores" are used to imply generality the design does not possess.
Missing generation, missing execution, and `ERROR` are reported in the
denominator as their own categories. [SPECIFIED]

### 5.7 Registration and release lineage

The draft defines three release stages to be frozen in sequence: R0
(registration: bases, generator,
catalog, oracle, compatibility matrix, environment identities), R1 (evidence:
confirmatory case archives and results, generated only after registration and
linked to the externally recorded R0 digest), and R2 (publication artifacts,
linked to both). Version identity uses an exact 18-field tuple; `latest` is
forbidden as an execution identity. Any R2 correction creates a new append-only
record with a new archive digest and version DOI, points to the immediately
prior R2 record, preserves the R0/R1 parents, and does not replace prior bytes.
[SPECIFIED]

## 6. Exploratory Case Study: A.M.Y, Atlas, and AXIOM (structure only)

<!-- STUB. This section reports L0 audit findings as exploratory evidence,
outside all confirmatory denominators. Content to be drafted from the
retained 2026-07-13 audit artifacts; every finding keeps its OBSERVED label
and artifact path. No finding here may migrate into Section 7. -->

- 6.1 System overview and release surface `[TODO]`
- 6.2 Working controls observed in code and artifacts `[TODO]`
- 6.3 Negative findings and narrowed claims `[TODO]`
- 6.4 What the case study cannot establish `[TODO]`

## 7. Results

`[RESULTS-FORBIDDEN-UNTIL-R1]`

<!-- FORBIDDEN-UNTIL-R1: This section must remain exactly the placeholder
line above until confirmatory execution completes under the frozen R0/R1
lineage. No provisional numbers, no synthetic-fixture numbers, no dummy
analysis output. The section skeleton (case-by-profile matrix, conformance
mismatches, target-invalid accepts by family, clean failures, environment
disagreements) is specified in PROTOCOL_DRAFT.md §11 and will be generated,
not written. -->

## 8. Discussion

`[DISCUSSION-FORBIDDEN-UNTIL-R1]`

## 9. Limitations and Threats to Validity

<!-- Derived from protocol/LIMITATIONS_AND_BOUNDARIES.md B1–B15. These are
boundary statements the paper must make regardless of results; they may be
drafted now. -->

The following limitations are design boundaries, not benchmark findings.
An authorized workflow can sign fabricated science, and P3 may correctly
accept it: release verification and scientific validity are separate
evaluations (B1). Complete compromise of the authorized builder identity
defeats signature-based distinction (B2). Availability is out of scope (B3),
as is rollback protection without separately trusted freshness state (B4).
Opaque cloud-model backends are recorded, not reconstructed (B5). The design
assumes the security of SHA-256 and the frozen signature stack rather than
demonstrating it (B6). Digests and signatures provide no confidentiality
(B7). Identity claims require an externally anchored trust policy (B8).
Reproduction claims for deterministic verifier decisions require byte-identical
normalized results; scientific-payload reproduction uses separately frozen
tolerances (B9). Source identity does not prove
historical truth of the development process, and the attested source archive
is bound as an opaque hashed file, not semantically reconstructed into the
asserted Git tree (B10). Passing every frozen case supports only the released
catalog version (B11). Model critiques are not independent human review
(B12). Once registered, the target contract is a normative policy, not a
measurable physical truth (B13). Filesystem-race freedom beyond the exercised
schedules is not claimed (B14). External R0-channel compromise is outside the
verifier's recovery capability (B15). [SPECIFIED]

## 10. Data and Artifact Availability

`[TODO-AT-R2: R0 registration DOI; R1 evidence deposit DOI; R2 publication
DOI; repository identity (commit and tree object IDs); archive SHA-256
values; license statements. Populated mechanically from the release-lineage
contract; hand-written identifiers are forbidden.]`

## 11. Conclusion

`[CONCLUSION-FORBIDDEN-UNTIL-R1-AND-EXTERNAL-REPRODUCTION]`

## References

Every entry below is a primary standard, official policy/documentation page, or
primary system paper. The fact licensed by each citation is narrowed in
`evidence/SOURCE_LEDGER.md`. [SPECIFIED]

- [S01] NIST, [FIPS 180-4: Secure Hash Standard](https://csrc.nist.gov/files/pubs/fips/180-4/final/docs/fips180-4.pdf).
- [S02] NIST, [FIPS 186-5: Digital Signature Standard](https://csrc.nist.gov/pubs/fips/186-5/final).
- [S03] NIST, [Digital Signatures](https://csrc.nist.gov/Projects/digital-signatures).
- [S10] in-toto, [Statement v1](https://github.com/in-toto/attestation/blob/main/spec/v1/statement.md).
- [S11] SLSA, [Build Provenance v1.2](https://slsa.dev/spec/v1.2/build-provenance).
- [S12] SLSA, [Build Track](https://slsa.dev/spec/v1.2/build-track-basics).
- [S13] SLSA, [Verifying Artifacts](https://slsa.dev/spec/v1.2/verifying-artifacts).
- [S15] Sigstore, [Verifying Signatures](https://docs.sigstore.dev/cosign/verifying/verify/).
- [S16] GitHub, [Artifact Attestations](https://docs.github.com/en/actions/concepts/security/artifact-attestations).
- [S20] OSF, [Registrations and Preregistrations](https://help.osf.io/article/330-welcome-to-registrations).
- [S21] ACM, [Artifact Review and Badging v1.1](https://www.acm.org/publications/policies/artifact-review-and-badging-current).
- [S22] Rundgren et al., [RFC 8785: JSON Canonicalization Scheme](https://www.rfc-editor.org/rfc/rfc8785.html).
- [S25] Sigstore, [Bundle Format](https://docs.sigstore.dev/about/bundle/).
- [S27] Secure Systems Lab, [DSSE Protocol](https://github.com/secure-systems-lab/dsse/blob/master/protocol.md).
- [S28] GitHub Actions, [`actions/attest` v4.1.1](https://github.com/actions/attest/releases/tag/v4.1.1).
- [S37] GitHub Actions, [Pinned `actions/attest` documentation](https://github.com/actions/attest/blob/a1948c3f048ba23858d222213b7c278aabede763/README.md).
- [S54] The Update Framework, [Specification v1.0.34](https://theupdateframework.github.io/specification/v1.0.34/index.html).
- [S55] Reproducible Builds, [Definition](https://reproducible-builds.org/docs/definition/).
- [S56] National Academies, [*Reproducibility and Replicability in Science*](https://nap.nationalacademies.org/catalog/25303/reproducibility-and-replicability-in-science).
- [S57] Center for Open Science, [Registered Reports](https://www.cos.io/initiatives/registered-reports).
- [S58] Lu et al., [*The AI Scientist: Towards Fully Automated Open-Ended Scientific Discovery*](https://arxiv.org/abs/2408.06292).
