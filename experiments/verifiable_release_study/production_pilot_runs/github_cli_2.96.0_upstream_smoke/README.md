# GitHub CLI 2.96.0 upstream Sigstore smoke test

Status: exploratory interoperability test only. This is not an A.M.Y
attestation, not a P3 result, and not confirmatory evidence.

The subject is the official `gh_2.96.0_linux_amd64.tar.gz` release asset from
`cli/cli` v2.96.0. Its official SHA-256 is
`83d5c2ccad5498f58bf6368acb1ab32588cf43ab3a4b1c301bf36328b1c8bd60`.
The public bundle was downloaded from GitHub's attestation API and verified
offline under trusted-root bytes produced by the exact pinned `gh` binary.
The retained verification was executed in the pinned Linux container with
Docker networking disabled.

This smoke test exercises the external cryptographic verifier and this study's
P2 post-verification policy adapter. It deliberately permits additional subjects
because the upstream release uses one Statement for all release assets. The
A.M.Y production template forbids additional subjects and requires a single
`MANIFEST.jcs.json` subject.

The P3 check is intentionally not run: the upstream predicate does not contain
the A.M.Y-specific clean-source and material fields. Passing P2 cannot be
reported as production P3 compatibility.

Expected retained files after the run:

- `inputs/attestation.sigstore.jsonl`
- `inputs/trusted_root.jsonl`
- `policy.json`
- `result.json`
- `input_hashes.json`

The 14 MiB subject is not duplicated here. Reproduction must download the exact
release asset and reject it unless its SHA-256 matches the value above.
