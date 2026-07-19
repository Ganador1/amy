# Confirmatory runner and outcome-guard contract — draft

Status: **NO-GO; engineering contract only; not frozen; no qualified external
human review; no confirmatory execution is permitted.**

This document narrows RG-006 into executable state and evidence contracts. It
does not upgrade the retained R0 review packet: that packet predates these
bytes and remains a valid historical, unreviewed preparation snapshot. A new
candidate packet and a new identity are mandatory before registration.

## 1. Security and scientific objective

The runner must prevent a scientific outcome from deciding whether another
attempt is made. The protected assets are:

1. the one-shot case and two-attempt authorized environment limits, while
   retaining any discovered unauthorized later attempt;
2. the identity of every attempted environment;
3. the official-attempt selection;
4. every raw output byte and every missing planned row;
5. the exact R0, runner, command, environment, policy, and schema identities;
6. the fact that selection was committed before any authorized result decode.

Local hashes establish byte identity only after somebody retains or
authenticates them. They do not prove when bytes existed, who produced them,
that provider metadata is truthful, that no hidden attempt occurred, or that
the operator did not obtain an outcome through another channel.

## 2. Conservative scientific boundary

`SCIENTIFIC_INTENT` is a durable event committed **before** spawning any case
generator or profile verifier. The presence of one such event permanently
forbids an environment retry, even if the child never starts, never writes a
result, crashes, or is killed before a terminal event. This closes the race
left by using only a terminal-event count.

Child return code, signal, duration, stdout/stderr availability, and output
size are outcome-side metadata after `SCIENTIFIC_INTENT`. None may make the
attempt retry eligible.

The only retry-eligible state is a pre-intent, pre-decode failure matching
exactly one of the four frozen infrastructure predicates. Missing,
contradictory, late, overlapping, or unauthenticated evidence is
`INVALID_CLASSIFICATION`; it never authorizes attempt two.

## 3. State machine

```text
NEW
  -> PREFLIGHT
  -> SCIENTIFIC_INTENT_DURABLY_PERSISTED
  -> CHILD_RUNNING
  -> RAW_BYTES_CAPTURED_OR_RETAINED_FAILURE
  -> ATTEMPT_RECORD_PERSISTED
  -> PREDECODE_CLASSIFICATION_PERSISTED

PREFLIGHT
  -> ELIGIBLE_PREINTENT_FAILURE
  -> ATTEMPT_RECORD_PERSISTED
  -> PREDECODE_CLASSIFICATION_PERSISTED
  -> ATTEMPT_2_AUTHORIZED_BY_CLASSIFICATION_SHA

ALL REQUIRED ENVIRONMENTS TERMINAL
  -> ONE CAMPAIGN SELECTION SEAL
  -> DETACHED AUTHENTICATION / EXTERNAL ANCHOR
  -> ONLY THEN: DECODE CAPABILITY MAY BE RELEASED
```

Any unknown transition, failed durability operation, evidence loss, attempted
preselection decode, or runner defect fails closed. Records are retained and
never repaired or replaced in place.

## 4. Closed record family

### 4.1 Environment-attempt record

`schemas/environment-attempt-record.schema.json` is outcome-free. It binds the
run policy, R0 lineage, registered inputs, command plan, runner, schema, exact
environment, and attempt number. It records typed infrastructure signals,
suspend-aware continuous time, a result guard, and raw artifact commitments.

Attempt one has no retry-authorization parent. A legitimate attempt two must
bind the SHA-256 of the already persisted attempt-one classification. An
unauthorized observed attempt two, or any attempt numbered 3–16, remains
representable and retained but can never replace an authorized official
attempt. The production policy still permits at most two authorized attempts;
the wider record range exists so violations cannot be erased from the seal.

The record may commit to opaque result bytes by raw SHA-256 and length. It must
not contain decoded decision, reason, expected label, oracle row, score, or
profile aggregate.

### 4.2 Pre-decode infrastructure classification

`schemas/infrastructure-classification.schema.json` binds the exact attempt
record and a canonical classifier-view projection. The projection includes
typed process-state metadata needed to reject contradictions such as
`PRESTART_ABORTED` plus `spawned=true`; it does not include process output,
result paths, oracle material, or decision fields. The classifier recomputes
the exact allowlisted top-level fields plus the nine allowlisted process
metadata fields; extra, missing, or outcome-bearing fields make the
classification invalid. The selector later recomputes both the
attempt and classification hashes from their exact JCS bytes. Its only
terminal states are:

- `RETRY_ELIGIBLE`: exactly one frozen pre-intent predicate matched;
- `NOT_RETRY_ELIGIBLE`: valid evidence exists but no retry predicate matched,
  including every post-intent state;
- `INVALID_CLASSIFICATION`: evidence, ordering, guard, or predicate evaluation
  is ambiguous or invalid.

The local continuous timestamp is audit metadata. Cross-process order comes
from parent hashes and guard checkpoints. Actual attempt-two authorization
requires detached authentication under a separately preauthorized identity;
that mechanism is not yet implemented.

### 4.3 Campaign-wide official-attempt selection seal

`schemas/official-attempt-selection.schema.json` covers `ENV-AUTHOR` and
`ENV-LINUX-PINNED` together. No result from the first environment may be
released while retry/selection remains open in the second environment.

The seal lists every discovered attempt, including unauthorized attempts, and
identifies at most one official attempt per environment. It contains only
candidate decode IDs. The actual outcome vault must require durable persistence
plus detached authentication/external anchoring before releasing plaintext.

## 5. Frozen selection table candidate

`E` means one valid retry-eligible pre-intent classification; `N` means a valid
non-retryable classification; `U` means invalid/indeterminate; `Ø` means absent.

| Attempt 1 | Attempt 2 | Official disposition |
|---|---|---|
| N | Ø | attempt 1 official |
| N | N | attempt 1 official; attempt 2 unauthorized and retained |
| N | E | attempt 1 official; attempt 2 unauthorized and retained |
| N | U | attempt 1 official; attempt 2 unauthorized and retained |
| E | Ø | no official attempt; authorized chain incomplete |
| E | N | attempt 2 official |
| E | E | no official attempt; both eligible failures retained |
| E | U | no official attempt; attempt-two classification invalid |
| U | Ø | no official attempt; no retry authorized |
| U | N | no official attempt; attempt 2 unauthorized |
| U | E | no official attempt; attempt 2 unauthorized |
| U | U | no official attempt; attempt 2 unauthorized |

The conservative `U` rule prevents invalid or pre-exposed evidence from being
promoted to confirmatory status. It is stricter than treating an invalid
classification as an ordinary non-retryable attempt.

## 6. Denominator mapping

No-official-attempt does not remove an environment from the planned product.
Every planned compatible unit/profile row for that environment becomes
`MISSING_EXECUTION` in the official observation ledger, with the campaign seal
and failed attempt-chain hashes retained separately. For an official incomplete
attempt, valid completed rows are retained and every unexecuted planned row is
`MISSING_EXECUTION`. Unauthorized attempt outcomes never enter the ledger.

The successor observation-ledger contract must add one design-level campaign
seal SHA-256 and, per row, the selected attempt ID and attempt-record SHA-256.
The analyzer must reject rows whose attempt is not selected by that seal. This
link is not implemented yet, so the current ledger remains unsuitable for R1.

## 7. Process primitive implemented so far

`amy_verifier/confirmatory_runner.py` currently implements only a synthetic
contract-test primitive. It:

- refuses `confirmatory_R1` classification;
- requires an absolute executable and externally supplied matching SHA-256;
- commits before spawn to the exact executable bytes, canonical argv,
  canonical environment, and working-root identity, and rechecks those
  commitments;
- uses an argv array with no shell, `stdin=DEVNULL`, `close_fds=True`, empty
  `pass_fds`, a literal environment mapping, `umask 077`, and a new session;
- uses Linux `CLOCK_BOOTTIME` or macOS `mach_continuous_time` and refuses an
  unsupported clock rather than silently downgrading;
- streams stdout/stderr as opaque bytes with per-stream and aggregate caps;
- sends TERM and then KILL to the process group even when the direct child has
  already exited but descendants retain stdout/stderr, applies a bounded final
  pipe-drain deadline, bounds every process wait, reaps the direct child, and
  recomputes elapsed time from the continuous clock;
- rereads sealed stdout/stderr and verifies their recorded lengths and SHA-256
  commitments before returning;
- opens attempt-store directory components without following symlinks, uses
  the platform's atomic no-replace rename (`renameat2(RENAME_NOREPLACE)` on
  Linux or `renameatx_np(RENAME_EXCL)` on Darwin), synchronizes file and
  directory descriptors, and verifies both the published bytes and visible
  directory-entry inode;
- records that same-UID write exclusion, transitive working-tree snapshotting,
  full process-tree containment, network isolation, filesystem sandboxing,
  external temporal order, signature authentication, operator identity,
  hidden-attempt absence, external outcome blindness, independent review, and
  RG-006 completion are all false.

These controls follow the narrow API properties documented by S47–S52. A new
session is not a PID namespace or cgroup. A process can attempt to escape its
group; same-UID permissions do not make output immutable against that UID; and
Docker `--network none` still has loopback (S53).

### 7.1 Typed policy and test binding

`protocol/RUN_EXECUTION_POLICY_DRAFT.json` now names the runtime predicate IDs,
the exact classifier projection, the pre-spawn intent rule, the two-attempt
parent-hash rule, and the campaign-wide selection rule. It binds 16 source,
schema, test, validator, manifest, and dependency-lock artifacts by SHA-256.
`development_checks/RG006_RUNNER_CONTRACT_TEST_2026-07-13.json` preserves the
historical 29-test v1 receipt. The v2 receipt dated 2026-07-14 is also preserved
but became historical when these bound contract bytes changed. The later v2
receipt dated 2026-07-15 is preserved under the same rule. The active
timestamped v3 receipt in `development_checks/` records the exact policy and
all 16 bound inputs used for 61 synthetic tests. Its source
inventory is hashed before and after pytest; any byte drift aborts receipt
creation, and exclusive creation prevents a later run from overwriting those
bytes. The suite includes later-attempt campaign sealing, process/state
contradictions, exact-record hash recomputation, inherited-pipe termination,
pre-spawn commitments, bounded waits, sealed-output rereads, classifier
projection, twelve injected storage-error cells, bounded transient/persistent
`EINTR`, same-UID directory-entry substitution, and three process-crash states
around atomic no-replace JCS publication.

Nine additional cells exercise a closed canonical `SCIENTIFIC_INTENT` event,
contiguous parent-hash reconstruction, process-receipt binding, three malformed
or ambiguous log states, cooperative append locking, failed-spawn retention,
publication failure before spawn, and a process crash after intent persistence
but before `Popen`. The final sequence-only event name is no-replace, so two
writers cannot retain two accepted events for one ordinal. The lock is advisory
and does not exclude a process with the same UID.

Those crash/storage tests establish only a partial atomic-publication control,
and the local intent chain establishes only a partial contract-test spawn gate.
They do not establish recovery after interruption, power-loss behavior,
cross-filesystem equivalence, unsupported-filesystem rejection, or coverage of
all runner persistence boundaries. The intent chain also has no authenticated
checkpoint, rollback detector, same-UID exclusion, recovery record, derived
classifier projection, or registered generator/profile adapter. All eleven
production controls therefore remain open, and a newly frozen receipt is still
required before R0.

The graph is deliberately acyclic: the policy binds its implementation and
validation inputs; the test receipt binds the exact policy tested; and the
policy-validation result binds both. The policy therefore does not contain the
hash of a receipt that itself contains the policy hash. Release manifests must
later commit the complete graph. This establishes reproducible byte identity,
not an authenticated production deployment or temporal order.

## 8. Required engineering work before freeze

1. Extend the partial local `SCIENTIFIC_INTENT` chain from the contract-test
   top-level spawn to the registered attempt state machine and every
   generator/profile adapter. Add an externally protected checkpoint, closed
   recovery receipt, rollback detection, and classifier inputs derived from
   scanned event bytes rather than caller-entered counters.
2. Run supervisor, classifier, sealer, and decoder under actual capability
   separation. The classifier must have no outcome/oracle path, FD, key, or
   decoding library access.
3. Add Linux PID namespace/cgroup containment and resource limits; establish a
   separately specified macOS/VM mechanism or declare ENV-AUTHOR incompatible.
4. Specify and test the offline boundary at OS level, including DNS, IPv4,
   IPv6, loopback, proxy, metadata IP, Unix sockets, and inherited sockets.
5. Extend the retained partial crash/ENOSPC/EDQUOT/EIO/EINTR campaign from the
   atomic JCS publisher to every runner write, sync, no-replace rename, raw
   stream, metadata, and directory-sync boundary; add recovery/quarantine and
   require unsupported filesystems to fail preflight. The current synthetic
   cells do not establish power-loss durability or cross-filesystem behavior.
6. Integrate the base-aware plan resolver into the future frozen runner and
   externally review its exact 246-row resolution. The same-worktree
   development resolver now consumes every base's mutation targets, resolves
   245 plans, and honestly marks B04 × `INVENTORY-OMIT-ROLE-001` unavailable;
   this does not itself authorize confirmatory generation.
7. Add separate child CLIs and a frozen normalization schema for S1 P0–P3 and
   production S2 P0–P3. Current production v2 covers only P2/P3.
8. Link the campaign seal to the observation ledger and carry the current
   synthetic coverage—12 table rows, overlaps, missing evidence, later
   attempts, outcome-field injection, child/grandchild hangs, and
   descriptor/environment canaries—into the frozen production adapters and
   fault-injection campaign.
9. Preauthorize and authenticate classifier/sealer identities, externally
    anchor the final campaign seal, rebuild a new exact-byte R0 review packet,
    obtain qualified non-implementer human review, and freeze/register it.

Until every item is closed, RG-006 and the study remain **NO-GO**.

## 9. Review provenance

This contract incorporates four parallel model-assisted same-worktree reviews:
repository integration, security, scientific retry logic, and schema/provenance
design. They were advisory and read-only. They are not qualified independent
human review and cannot satisfy RG-004 or RG-006.
