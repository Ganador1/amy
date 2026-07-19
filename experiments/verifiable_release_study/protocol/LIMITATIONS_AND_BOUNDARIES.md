# Limitations and Boundary Cases

Version: `0.3.0-draft`

These are not benchmark attacks and do not enter any target-miss denominator.
They define what the paper must not claim.

## B1 — Authorized scientific falsehood

An authorized workflow can sign internally consistent fabricated data or an
unsound analysis. P3 may correctly accept the package because cryptographic and
provenance policy passed. Scientific controls are open raw evidence, registered
analysis, independent review, and reproduction.

Permitted wording: “The release identity and bytes were verified; scientific
validity was evaluated separately.”

## B2 — Compromised authorized builder

If an attacker controls the authorized CI identity and all machine-checkable
policy fields, signatures alone cannot distinguish the attacker from the
authorized workflow. Hardware isolation, least privilege, two-person release
review, monitoring, and revocation can reduce but not eliminate this risk.

## B3 — Availability

Deleting an entire release prevents verification but does not create a verifier
decision. Redundant DOI archives and mirrors address availability. No checksum or
signature guarantees retrieval.

## B4 — Rollback without trusted state

An old signed release remains valid. Without a separately trusted expected
version/digest/checkpoint, P3 cannot know that it is stale. The primary study
does not claim replay or rollback protection.

## B5 — Opaque cloud-model drift

The released request and response bytes can be hashed and authenticated. Hidden
weights, routing, moderation, caches, and serving code cannot be reconstructed
without provider evidence. A repeated call is a new observation, not proof of
the original backend.

## B6 — Hash and signature assumptions

The design relies on full SHA-256 collision/second-preimage resistance and the
security assumptions of the frozen signature stack. The benchmark tests binding
logic and implementation behavior; it does not empirically prove the
cryptographic primitives secure.

## B7 — Confidentiality

Digests, signatures, and attestations do not encrypt payloads. Sensitive or
restricted data requires a separate governance and confidentiality design.

## B8 — Identity outside the package

A self-generated key plus fingerprint proves only consistency with that key. A
claim about Ganador1/A.M.Y requires an independently anchored repository/workflow
or public-key trust policy.

## B9 — Reproduction versus bitwise identity

Deterministic verifier decisions can be byte-for-byte reproduced. Scientific
floating-point/model outputs may require frozen tolerances. “Reproduced within
tolerance T under environment E” is not “universally 100% reproducible.”

## B10 — Source identity versus historical truth

A Git object ID and exported source SHA-256 identify bytes. They do not prove
that all relevant work happened in Git, that timestamps are truthful, or that a
dirty/unrecorded input never affected an earlier result.

The selected P3 profile also treats the exported tar as an opaque hashed file.
It does not establish that the tar members reconstruct the separately asserted
Git tree. Such a statement is prohibited unless a future, independently tested
tree-equivalence verifier is added under a new profile version.
The controlled S1 snapshot is now a syntactically valid deterministic USTAR;
that format check prevents a mislabeled fixture but does not expand the P3
assurance beyond exact-byte digest and payload-role binding.

## B11 — Catalog coverage

Passing every frozen case supports only “all compatible cases in catalog version
X.” Unlisted compound attacks, implementation vulnerabilities, future standard
changes, or operational compromise remain possible.

## B12 — Independent review

Ten model critiques are not ten independent scientific reviewers: they may share
training data, provider infrastructure, and correlated biases. Independent
artifact validation requires a separate person/team or clearly disclosed weaker
substitute.

## B13 — Normative target and corpus external validity

The target decision is a preregistered, standards-grounded policy judgment, not
an independently measurable physical truth. P3 is designed to implement that
policy, so a conforming P3 result is not evidence that P3 covers threats omitted
from the policy. Independent oracle review can detect inconsistency and bias but
cannot turn a finite designed catalog into a representative sample of all future
attacks.

## B14 — Concurrent mutation and filesystem semantics

Confirmatory packages are private immutable snapshots. The implementation uses
descriptor-relative traversal, non-following opens, pre/post-read metadata
checks, and a final payload-tree identity rescan. A separate pre-registration
engineering stratum exercises seven scheduled temporal mutations and five
injected failures in the author and pinned Linux environments. The primary
catalog still does not claim exhaustive protection against every interleaving,
metadata-restoration attack, network filesystem behavior, kernel defect, or
hostile storage layer. General filesystem-race freedom remains an explicit
non-benchmark boundary.

## B15 — Policy bootstrap and external R0 trust

V2 prevents a local policy/schema substitution only when the operator supplies
the expected policy SHA-256 from an authentic immutable R0/deposit channel. If
an attacker controls that external expected value as well as the local policy,
schemas, verifier, and trusted root, the local digest chain cannot recover
authorization. The benchmark can test correct comparison and binding behavior;
it cannot make the registry/DOI channel self-authenticating or prove that an
operator selected the intended R0.
