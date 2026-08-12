# Pinned `actions/attest` Semantics Audit

Status: exploratory design audit; production P3 remains unrun.

The exact `actions/attest` v4.1.1 commit selected by this study delegates its
default provenance construction to `@actions/attest` 3.2.0. Its bundled code
generates SLSA provenance with build type
`https://actions.github.io/buildtypes/workflow/v1`, a single
`externalParameters.workflow` object, one resolved Git dependency keyed by
`gitCommit`, and a builder derived from the OIDC `job_workflow_ref`.

It does not generate the current A.M.Y fields
`externalParameters.source.dirty`, `amy:source-snapshot`,
`amy:dependency-lock`, or the selected execution-image dependency. The action's
custom mode can sign a workflow-supplied predicate, but cryptographic
authentication of that predicate does not make its contents independent of the
authorized workflow.

Therefore the current P3 adapter is incompatible with the pinned default
predicate. This is a registration blocker, not a failed experiment. The
candidate resolution profiles and their tradeoffs are recorded in
`protocol/ATTESTATION_PROFILE_DECISION_DRAFT.json`; none is frozen.

Primary sources:

- [Exact `actions/attest` commit](https://github.com/actions/attest/commit/a1948c3f048ba23858d222213b7c278aabede763)
- [Pinned action provenance wrapper](https://github.com/actions/attest/blob/a1948c3f048ba23858d222213b7c278aabede763/src/provenance.ts)
- [Pinned action README: default and custom modes](https://github.com/actions/attest/blob/a1948c3f048ba23858d222213b7c278aabede763/README.md)
- [SLSA build-provenance schema and trust model](https://slsa.dev/spec/v1.2/build-provenance)
- [SLSA artifact-verification guidance](https://slsa.dev/spec/v1.2/verifying-artifacts)
- [GitHub warning on attestation scope](https://docs.github.com/en/actions/concepts/security/artifact-attestations)

The JSON companion retains exact upstream hashes, the bundled dependency
version, reproducible inspection commands, observed fields, and limitations.
