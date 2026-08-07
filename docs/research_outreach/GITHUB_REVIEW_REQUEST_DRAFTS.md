# External review requests and routing drafts

Status checked against the public project pages on 2026-08-07. The OpenSSF and
in-toto routing requests have been published; the ReSA text remains draft-only.
Do not repost a published body or send the remaining draft without checking the
destination's current process.

## Current public status

- **Central tracker:** <https://github.com/Ganador1/A.M.Y/issues/11> remains
  open and explicitly `NO-GO`. The frozen candidate is
  `pre-r0-review-2026-07-18.1` at source commit `2e0738c38653682cc80c9a44c6ad3fcb732e6eb1`;
  its packet SHA-256 is
  `85bd38c39de65ed41401fbd8e4dd9647426f4d33a1685a9874aa7e3db6524098`
  and its subject-manifest SHA-256 is
  `95bc17435811a259d079176df8004989409df34f58b1d7c5f0005d3653a171fd`.
  Ten blocking registration gates, 17 closure requirements, 54 compatibility
  rows, and 47 TBD markers remain open. No confirmatory benchmark, detached
  signature, or authorized human-review record exists.
- **OpenSSF:** published on 2026-07-19 as
  <https://github.com/ossf/wg-supply-chain-integrity/discussions/87>. It is
  still marked `Unanswered`; its only comment is the author's correction from
  the superseded release URL to `.1`. Do not post the draft below again.
- **Local reviewer recruitment:**
  <https://github.com/Ganador1/A.M.Y/discussions/12> has zero comments and one
  participant.
- **Implementation PR:** <https://github.com/Ganador1/A.M.Y/pull/10> remains a
  draft with no reviews. Newer branch commits remain outside the frozen `.1`
  review subject until a new packet and byte identity are explicitly created;
  updating the PR branch does not silently redefine the frozen candidate.
- **in-toto:** A.M.Y posted the routing request on 2026-07-19 at
  <https://github.com/in-toto/attestation/issues/565#issuecomment-5013940356>.
  Proposal author `b7n0de` replied with a composition-by-digest recommendation
  at <https://github.com/in-toto/attestation/issues/565#issuecomment-5014647211>;
  A.M.Y accepted that boundary and repeated its maintainer-routing question at
  <https://github.com/in-toto/attestation/issues/565#issuecomment-5016458855>.
  No maintainer has answered that routing follow-up. Implementation PR
  <https://github.com/in-toto/attestation/pull/575> is open and mergeable but
  blocked, with no reviews or requested reviewers as of this check. A new
  external comment by `ppcvote` at
  <https://github.com/in-toto/attestation/issues/565#issuecomment-5214755378>
  correctly notes that harness identity does not establish detector capability
  and proposes optional sensitivity/specificity metadata. This is relevant
  technical input, not a maintainer decision or formal review. A.M.Y replied on
  2026-08-07 at
  <https://github.com/in-toto/attestation/issues/565#issuecomment-5216804741>
  with the tested local contract from commit
  `1e1d5056bac1cbfecea483a684aff5d5440d6a19`, its conservative policy, and a
  question about using a typed `characterizationRef` digest instead of inline
  floats. That response is awaiting external follow-up.
- **ReSA:** no sent request is recorded locally. Its community-call page did
  not expose a scheduled upcoming call during the 2026-08-06 check; use the
  official contact route and verify again immediately before sending.

The lack of replies is not evidence of review, approval, compatibility, or
scientific validity. Follow-up should identify the exact frozen bytes and ask
for routing or falsification, not endorsement.

These requests deliberately ask for criticism of a bounded protocol. They do
not claim that the protocol proves scientific truth, that registration has
occurred, or that a private repository is independently reproducible.

## Recommended routing

- **in-toto Attestation Framework:** do not plan on opening a new issue:
  <https://github.com/in-toto/attestation/issues> currently reports that issue
  creation is restricted. The closest active discussion is
  <https://github.com/in-toto/attestation/issues/565>, an `eval-result`
  predicate proposal that explicitly separates a signed evaluation claim from
  truth, safety, and authorization. Start with a concise, non-hijacking comment
  asking whether this use case belongs there, or ask in the documented
  `#in-toto-attestations` Slack channel. Review the current vetted Release,
  Runtime Traces, SCAI Report, Simple Verification Result, and Test Result
  predicates plus the New Predicate Guidelines before proposing a new type.
- **OpenSSF Supply Chain Integrity WG:** use a
  <https://github.com/ossf/wg-supply-chain-integrity/discussions> post or ask
  for agenda time through the WG's public
  <https://lists.openssf.org/g/openssf-supply-chain-integrity> list or
  `wg_supply_chain_integrity` Slack channel. Its public page currently lists a
  meeting every other Wednesday at 09:00 Pacific. The repository is a
  community coordination space, not an implementation bug tracker.
- **Research Software Alliance (ReSA):** do not open the request against
  `researchsoft/website`; that repository tracks website content. Use a ReSA
  community call, Slack, or the official contact route at
  <https://www.researchsoft.org/about/contact/> instead.

## Sent request — in-toto/attestation issue #565

The short opening comment was sent on 2026-07-19. The longer context remains
historical draft material and must not be posted without a direct invitation.

### Short opening comment

We are testing a related but narrower computational-research case: a signed,
versioned evidence packet that binds test results, execution/recovery records,
and explicit claim boundaries, while treating truth, benchmark validity,
authorization, and freshness as separate properties. Before writing a format,
would maintainers prefer that we compose the existing Test Result, Runtime
Traces, Release, and Simple Verification Result predicates; align with the
proposed `eval-result`; or bring a concrete schema to the
`#in-toto-attestations` meeting/Slack channel? We do not want to duplicate this
proposal or turn an application profile into a new general predicate.

### Longer context, only if invited

We are designing a small, preregistered study of verifiable release packets for
computational research. Before freezing the confirmatory release, we would
value an adversarial review of our use of DSSE and in-toto Statements.

The bounded use case is:

1. A beta system changes frequently.
2. Each study candidate is frozen as a byte manifest plus archive; later
   candidates create new identities and never replace an earlier candidate.
3. The attestation subject is the digest of the released packet. A source Git
   commit is recorded as metadata, but is not treated as sufficient when the
   evaluated snapshot contains dirty or untracked bytes.
4. The predicate records the protocol/profile version, runner intent, execution
   attempt, recovery classification, verifier results, and explicit claim
   boundaries.
5. A signature is treated only as evidence that a key signed specific bytes.
   Authorization is a separate policy decision. Integrity, provenance,
   freshness/rollback protection, reproducibility, and scientific truth are
   separate properties.
6. DSSE alone is not claimed to prevent rollback. Any freshness claim would
   require an external transparency-log checkpoint or equivalent trusted state.

Questions:

- Is a composition of existing in-toto predicates appropriate for this
  evidence packet, or is a dedicated application profile justified?
- Should the packet digest be the only Statement subject, with source commit,
  source-tree digest, and predecessor packet digest in the predicate?
- What is the least misleading way to represent a release lineage when beta
  candidates are produced often?
- Which fields should be verifier-computed rather than producer-declared?
- Are we missing a binding needed to connect spawn intent, attempt, recovery
  record, and final classification?
- Which negative tests would you require before considering the format
  interoperable?

The review artifact can contain schemas, canonical test vectors, verifier
commands, expected failures, and a threat model. It will not contain private
keys, credentials, unpublished model outputs, or claims of scientific
validation. We will share its URL and exact SHA-256 only if maintainers invite
the longer review:

`PUBLIC_REVIEW_PACKET_URL: pending`

`PUBLIC_REVIEW_PACKET_SHA256: pending`

We are especially interested in findings that would falsify our current design,
not endorsement. If this belongs elsewhere, a routing pointer is sufficient.

## Published request — OpenSSF Supply Chain Integrity WG

Published at <https://github.com/ossf/wg-supply-chain-integrity/discussions/87>.
The text below is retained as a historical source, not as a request to repost.

### Title

Request for threat-model review: versioned, attestable evidence packets for
computational research

### Body

We are preparing a preregistered, negative-test-driven study of release
integrity for computational research artifacts. We would appreciate review from
the Supply Chain Integrity WG on the threat model and claim boundaries before
we freeze the confirmatory packet.

The narrow question is how to publish frequently changing beta research
software and evidence without making a Git commit, checksum, or signature carry
claims it cannot support.

Our current boundaries are:

- a commit SHA identifies a Git object, but not dirty or untracked evaluated
  bytes;
- a packet manifest binds the released bytes;
- a DSSE signature authenticates signed bytes under a key, subject to a
  separate authorization policy;
- neither a hash nor a signature establishes scientific correctness;
- rollback/freshness requires trusted state outside the packet;
- each beta candidate receives a new packet identity and an explicit
  predecessor link; prior packets are not silently rewritten;
- failed, timed-out, partial, and recovered executions are distinct states and
  must not be summarized as successful evidence.

We seek concrete criticism on:

1. missing attacker capabilities or trust boundaries;
2. ambiguous uses of “provenance”, “verified”, “reproducible”, or
   “authenticated”;
3. minimum negative tests for substitution, replay, rollback, TOCTOU,
   canonicalization, and partial-execution attacks;
4. whether our release-lineage and checkpoint model is sufficient for an
   honest beta workflow;
5. the smallest public review packet that would allow useful independent
   review without publishing the full private repository.

We will attach a scrubbed packet only after it has a stable URL and digest:

`PUBLIC_REVIEW_PACKET_URL: pending`

`PUBLIC_REVIEW_PACKET_SHA256: pending`

This is a request for technical review, not a request for endorsement or a
claim that the protocol is already production-ready.

## Publication checklist

- Replace both `pending` fields with one immutable public artifact URL and its
  independently recomputed SHA-256.
- Verify the packet from a clean environment using only documented commands.
- Remove absolute local paths, usernames, credentials, private repository URLs,
  unpublished scientific results, and unnecessary model transcripts.
- Include a license, contribution instructions, and a security contact.
- State the tested platform matrix and all untested platforms.
- Include expected-failure vectors; a success-only demo is insufficient.
- Search existing issues before posting and link any overlapping discussion.
- Post one focused request per community; do not cross-post identical text.
- For in-toto, ask for routing first; do not paste the long request into issue
  #565 unless its participants invite that scope.

## Follow-up checklist

- Do not count a self-authored correction, reaction, or silence as external
  review.
- Before an OpenSSF follow-up, verify that discussion #87 is still unanswered,
  then ask once for the appropriate meeting or narrower channel instead of
  repeating the full request.
- Do not resend the in-toto routing question. Track maintainer routing and PR
  #575 separately from useful comments by non-maintainers.
- For ReSA, use the official contact route or a confirmed community call; keep
  the ask focused on research-software reproducibility and archival practice.
- Record every sent request here with date, immutable URL, destination,
  response status, and exact packet/source hashes presented for review.
