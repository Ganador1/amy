# Production GitHub/Sigstore Gate Draft

Prepared: 2026-07-13  
Status: selected-profile implementation draft; real upstream P2 smoke complete;
A.M.Y P3 not run

## 1. What this gate can establish

The gate is designed to establish that exact `MANIFEST.jcs.json` bytes were
attested by an authorized GitHub Actions identity at an evidenced time and that
the authenticated provenance satisfies a frozen policy. P3 then independently
validates the manifest inventory and every payload digest.

It cannot establish that an authorized workflow was honest, that omitted data
never existed, or that a scientific conclusion is true. GitHub explicitly
warns that predicate content can be falsified by a compromised workflow even
when the certificate and timestamps are authentic.

## 2. Frozen tool candidates

The draft selects exact upstream objects observed on 2026-07-13:

| Component | Human release | Normative identity |
|---|---|---|
| `actions/checkout` | `v7.0.0` | `9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0` |
| `actions/attest` | `v4.1.1` | `a1948c3f048ba23858d222213b7c278aabede763` |
| `actions/upload-artifact` | `v7.0.1` | `043fb46d1a93c77aae656e7c1c64a875d1fc6a0a` |
| GitHub CLI | `2.96.0` | source commit `b300f2ec7ec9dc9addc39b2ad88c54097ded7ca0` |
| `gh` Linux archive | `2.96.0 linux amd64` | SHA-256 `83d5c2ccad5498f58bf6368acb1ab32588cf43ab3a4b1c301bf36328b1c8bd60` |
| extracted `gh` binary | same archive | SHA-256 `56b8bbbb27b066ecb33dbef9a256dc9d1314adaeff0908a752feba6c34053b40` |
| verification image | `uv 0.9.17`, Python 3.12.12, bookworm-slim | Linux/amd64 manifest `sha256:c8367d14e6e5f9311689792032852506d7188f487c6db2967c386a26ebeecff1` |

Release labels are comments for maintenance. Workflows use only the full commit
after confirming it belongs to the official repository. A future security
update changes the workflow, policy, protocol version, and evidence; a moving
major tag is never silently accepted.

The current repository workflows still use mutable major-version tags. They are
not approved as the scientific release builder.

## 3. Proposed release-specific identity

The machine-readable template is
`protocol/GITHUB_ATTESTATION_POLICY_TEMPLATE_V2.json`, validated by
`schemas/github-attestation-policy-v2.schema.json`. A release instance must
replace every `TBD-BEFORE-REGISTRATION` value and then freeze its own SHA-256.
Required values include:

- canonical repository `Ganador1/amy` (matching the configured remote and the
  case-sensitive identity expected from the future certificate);
- exact source commit and tag ref;
- exact certificate SAN, including workflow path and ref;
- exact signer-workflow commit and source commit, even when equal;
- public GitHub OIDC issuer and GitHub-hosted runner;
- public Sigstore certificate-authority profile and Rekor Tlog witness;
- exact trusted-root bytes and independently recorded root digest;
- one SHA-256 subject named `MANIFEST.jcs.json`;
- exact default SLSA predicate, source dependency, and builder values;
- exact authenticated-manifest source/tree/clean-state, lockfile, source
  snapshot, and execution-image values.

`--cert-identity` is used instead of `--signer-workflow` because the latter is a
prefix policy in the inspected GitHub CLI implementation. Expected values come
from the frozen policy, never from the bundle under test.

The expected policy SHA-256 is not learned from that policy or bundle. The v2
CLI requires it as a separate argument sourced from the immutable R0/deposit
identity. Once those exact policy bytes are authorized, the policy itself binds
the exact policy-schema, terminal-result-schema, trusted-root, manifest-schema,
tool, workflow, and action bytes. The v1 policy/schema/CLI and real GitHub-CLI
P2 smoke remain byte-preserved historical evidence and are not silently
upgraded into v2 evidence.

## 4. Production construction sequence

1. Trigger only from a release-specific tag namespace, not a branch tip.
2. Check out the exact event commit with credentials disabled.
3. Confirm that HEAD, event SHA, source policy, and tag target agree.
4. Confirm no tracked or untracked working-tree changes before generation.
5. Run the registration-ready validator and P1 release validation in the
   digest-pinned Linux image.
6. Generate the final source archive, lock digest, and v0.2 build metadata from
   fixed inputs. Mark these fields as workflow-authored assertions.
7. Attest only the final `MANIFEST.jcs.json` using the full `actions/attest`
   commit. Copy its `bundle-path` output before the runner exits.
8. Download/archive the exact trusted-root material and record its SHA-256
   through an independent release record.
9. Run P3 offline with networking disabled and the pinned `gh` binary.
10. Assemble the outer transport archive, compute its SHA-256, reproduce in a
    clean environment, and only then publish a draft release's complete assets.
11. Publish after GitHub release immutability has been enabled; independently
    deposit the same bytes under a version-specific DOI.

The exact pinned default provenance produced by `actions/attest` records
workflow information and one resolved Git dependency but does not encode
A.M.Y-specific clean/tree/snapshot/lock/image fields. The pre-selection mismatch
is retained in
`audit/UPSTREAM_ATTESTATION_SEMANTICS_2026-07-13.json`.

Before confirmatory execution, the project selected preservation of the
unmodified default GitHub SLSA predicate plus schema-validated A.M.Y assertions
inside the exact manifest bytes authenticated as its sole subject. The
production v0.2 schema labels those values
`workflow-authored-not-independently-certified` and cross-binds source snapshot
and dependency lock metadata to payload entries. The other three candidates
remain in the decision record. Selection is not freeze or validation: real
A.M.Y controls and independent human review remain blocking. The controlled S1
migration now covers six clean bases, all 41 generic temporary-fixture mutation
branches, a schema-closed 164-row catalog-derived draft oracle, and a 246-row
compatibility product. This still does not create the frozen six-base case
corpus: proposition/oracle independent review, pending prerequisite resolution,
and the post-registration runner remain incomplete.

The snapshot field is intentionally limited to opaque exact-byte assurance.
P1/P3 recompute its SHA-256, but this profile does not parse tar members or
certify equivalence between that tar and the separately asserted Git tree.

## 5. Offline verification policy

The current entry point is `scripts/verify_github_attestation_v2.py`. Its v2
policy layer in `amy_verifier/github_attestation_v2.py` wraps the byte-preserved
cryptographic/P1 core in `amy_verifier/github_attestation.py` and performs the
following:

1. Requires an externally supplied expected policy SHA-256 and compares it to
   the exact bounded policy bytes before policy use.
2. Strictly parses the policy and its exact hash-bound Draft 2020-12 schema,
   rejecting duplicate keys, unknown fields, malformed values, schema
   substitution, template status, prerelease frozen-policy versions, and every
   unresolved release placeholder.
3. Retains immutable raw policy, policy-schema, and result-schema byte
   snapshots and reparses, rehashes, and revalidates them at each library
   verification call so a mutable parsed dictionary cannot be altered after
   validation; library `ACCEPT` serialization is checked against those exact
   result-schema bytes.
4. Reads bounded regular files without following symlinks and snapshots their
   bytes.
5. Rejects a trusted-root digest different from the frozen policy.
6. Reads and hashes the `gh` executable, copies those exact bytes to a private
   temporary file, and executes only that copy.
7. Clears GitHub authentication tokens and isolates CLI configuration.
8. Invokes `gh attestation verify` with local bundle and custom trusted root,
   exact certificate identity, repository, issuer, signer/source commits, ref,
   predicate, hosted-runner requirement, and JSON output.
9. Requires exactly one verified attestation result.
10. Rechecks result and bundle media types, certificate fields, public Rekor
   witness, Statement type, and exact subject digest.
11. For P3 only, checks the standard predicate's workflow, builder, and sole
   source dependency, then checks authenticated-manifest source/clean/tree/
   snapshot/lock/image assertions.
12. Cross-binds source snapshot and lock to their declared payload roles and
   executes canonicality, production schema, path, role, closed-world inventory,
   byte-size, and full SHA-256 checks over every current payload.
13. Re-reads the manifest after P1 and rejects `INPUT_CHANGED` if its bytes
    differ from the attested snapshot.
14. Requires policy, policy-schema, and result-schema SHA-256 in every terminal
    `ACCEPT`, `REJECT`, or `ERROR`, validates that object against the exact
    result schema, and emits no structured stdout if the complete contract was
    not established first.

Step 12 treats `source.tar` as an opaque payload. Any future semantic
tree-reconstruction check is a new, separately specified profile revision, not
an implication of the current signature.

For the A.M.Y profile, additional Statement subjects are forbidden. P2 uses an
untrusted preparse only to select the candidate signed `predicateType`; it does
not accept that value as authenticated until `gh` succeeds.

The lower-level attestation API accepts only P2. A caller requesting production
P3 must use `verify_github_p3_release` (or the CLI with `--profile P3` and
`--manifest-schema`); this prevents attestation-only success from being
misreported as integrated payload verification.

For v2, callers use `verify_github_manifest_attestation_v2` or
`verify_github_p3_release_v2` with a `GitHubPolicyDocumentV2` produced by the
externally pinned loader. Passing a plain mutable policy dictionary is rejected.

The future frozen P3 command contract is:

```text
python scripts/verify_github_attestation_v2.py <release-root> <policy-v2.json> <trusted-root.jsonl> \
  --profile P3 \
  --expected-policy-sha256 <sha256-from-R0> \
  --policy-schema schemas/github-attestation-policy-v2.schema.json \
  --manifest-schema schemas/manifest-production-v0.2.schema.json \
  --result-schema schemas/github-production-verification-result-v2.schema.json \
  --gh <exact-pinned-gh-binary>
```

The command is documentary while the policy remains a template; invoking it
with the current template must terminate as a schema-valid `ERROR` before any
bundle or payload verification.

## 6. Completed real-crypto smoke and its boundary

`production_pilot_runs/github_cli_2.96.0_upstream_smoke/` retains a real public
Sigstore bundle for the official GitHub CLI 2.96.0 Linux asset, current trusted
root bytes, policy, and result. The pinned Linux `gh` verifier accepted the
asset offline with Docker networking disabled. Two same-environment executions
produced byte-identical result JSON.

This establishes limited P2 interoperability with a real PGI certificate and
Rekor evidence. It does **not** establish any of the following:

- that A.M.Y has a valid production attestation;
- that the selected manifest-metadata P3 profile is generated correctly;
- that P3 works against a real A.M.Y release;
- that a separate party reproduced the result;
- that the trusted-root bootstrap is independently established;
- that the confirmatory corpus is ready.

Those statements remain prohibited until a clean public workflow run and an
independent Linux reproduction are archived.

## 7. Mandatory negative tests before registration

- changed manifest bytes under the original bundle;
- changed bundle signature, certificate, transparency entry, and Statement;
- correct signature from the wrong repository/workflow/ref/commit;
- self-hosted runner when policy requires GitHub-hosted;
- correct authenticated manifest with changed payload bytes;
- coherently replaced payload and unauthenticated manifest;
- wrong/omitted source dependency, manifest build metadata, dirty state, Git
  tree, lock digest, source snapshot, cross-bound payload role, image digest,
  builder, or predicate type;
- an attestation-only caller attempting to label its result P3;
- stale trusted root, wrong root, missing root, and multiple verified bundles;
- offline rerun with all networking disabled;
- exact-output comparison under a second clean Linux execution.

Any `ERROR` is an infrastructure/verifier failure, not a successful rejection.
