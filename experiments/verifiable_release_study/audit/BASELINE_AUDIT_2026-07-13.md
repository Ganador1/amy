# Exploratory Baseline Audit — 2026-07-13

Status: exploratory; performed before preregistration  
Audit instant: `2026-07-13T04:33:43Z`  
Repository root: `/Volumes/Ganador disk/A.M.Y`

This is an audit of observed repository behavior and bytes, not a review of
documentation claims. It is intentionally preserved as pre-study context and
must not be counted as confirmatory benchmark data.

## Snapshot identity

- Branch: `codex/amy-scientific-quality-gates`
- HEAD: `40663854cfc2a2cf8e8e828cc0ac7c031db58963`
- Describe: `v1.0.0-68-g4066385-dirty`
- Tracked changed files: 10
- Untracked status entries: 276
- Declared A.M.Y version: `1.0.0` in both `pyproject.toml` and `amy.py`
- Declared Atlas version: `4.1.0`
- Last 10 commits: all Git signature status `N` (no signature)
- Tag `v1.0.0`: annotated, but `git verify-tag v1.0.0` returned
  `error: no signature found`
- Public origin: `https://github.com/Ganador1/amy` (observed public)
- Public `main` at audit: `17ae5de5fbfe0ab4a6eb6d40064a4db2a9f4136e`
- Local HEAD versus local `origin/main`: 0 commits behind, 11 commits ahead
- Public annotated tag object `v1.0.0`:
  `296638caf7fa08909c7b4c32e96d82600b081487`; peeled commit:
  `bec467d0053196516acd1322e740c5c9be958cd7`

Because the tree is dirty, HEAD alone does not identify all audited source
bytes. Relevant file SHA-256 values are recorded at the end of this report.

## Summary of findings

| ID | Finding | Evidence | Consequence |
|---|---|---|---|
| F01 | Historical A.M.Y output hashes are internally consistent | 1,653/1,653 `output.txt` SHA-256 values matched `tool.output_hash`; no missing outputs | Strong evidence of current byte consistency, but not signer authenticity |
| F02 | Provenance verification does not verify bytes | `core/provenance.py::verify_experiment_id` checks presence/JSON readability but does not recompute `output.txt` SHA-256 | A verification call can report success after payload modification |
| F03 | Paper provenance display trusts stored hash text | `_provenance_output_hash` validates only 64-hex syntax | Paper watermarking is a self-check, not authenticated provenance |
| F04 | HMAC provenance functions are not integrated into production records | Search found calls only in hardening tests; 0/1,653 records contain signature/HMAC/security blocks | Current records are unsigned; fallback key is process-ephemeral when the environment key is absent |
| F05 | Current Ed25519 manifest signatures are cryptographically valid under local keys | 3/3 manifests report one valid signature and no signature errors | This validates signed manifest bytes only |
| F06 | A valid signed manifest coexists with an invalid referenced artifact | `plausibility_v4_rf.pkl` expected `96620b6d...d32fe`, actual `83361476...fdf85` | Signature-only verification produces a security-relevant false positive if called “artifact valid” |
| F07 | Public trust material is unavailable to a normal clone | `atlas/.gitignore` ignores all `keys/`; public and private keys are local | External users cannot establish or reproduce the local trust decision |
| F08 | Local signing key handling is unsafe for publication identity | Private key is unencrypted by the signing script and mode `0644` | Other local users may read it; the identity must not be used as a public release trust root |
| F09 | Manifest self-hash rules are inconsistent/self-referential | All 3 stored manifest hashes fail both active validator calculations; one validator includes the stored hash while hashing | Tools can disagree or require an impossible self-referential fixed point |
| F10 | Artifact path resolution is inconsistent | Manifest paths start `models/...`; one validator resolves them from `atlas/models`, producing `atlas/models/models/...` | Valid artifacts can be falsely reported missing |
| F11 | “Blockchain” validation is a local simulation | In-memory Python list, local SHA-256 links, small proof-of-work, fixed confidence `0.5`; no active signature generation/verification | It must not be described as distributed blockchain validation or independent consensus |
| F12 | Integrity records default to valid | `integrity_core.py` assigns `integrity_status="valid"` when creating records | Existence/self-report can be mistaken for actual verification |
| F13 | One current scientific release manifest is fully consistent | SSH release: 24/24 entries verify | This is a positive control for manifest generation |
| F14 | A.M.Y system-paper release changed after manifest generation | Main manifest: 1,135 OK, 13 failed; payload manifest: 1,133 OK, 13 failed | That release is not currently byte-verifiable against its published manifests |
| F15 | Observable Ollama client/server versions disagree | server `0.31.2`; client warning says `0.17.4` | Model-call records must retain both values and cannot trust a single version label |
| F16 | The audited source is not publicly reconstructible from current `main` alone | Local HEAD is 11 commits ahead of `origin/main` and the tree is dirty | A public CI attestation cannot yet identify the audited local state |
| F17 | Public wording is broader than the observed implementation | The [public README](https://github.com/Ganador1/amy) describes cryptographic provenance and fully verified tools, while current production provenance records have hashes but no signatures and Atlas signature checks are decoupled from artifact checks | Claims must be narrowed to the exact mechanism and audit scope until integrated verification exists |

## Detailed cryptographic distinction

The local signature verifier signs and verifies canonicalized manifest JSON with
the top-level `signatures` field removed. It does not verify the files listed by
that manifest. Therefore these two statements are simultaneously true:

1. all three tested Ed25519 signatures verify under the local public key;
2. one of the three referenced model artifacts fails its recorded SHA-256.

Calling the second artifact “valid” from the first result alone would be false.
The new verifier must expose separate results for payload integrity, signature
cryptography, signer authorization, provenance policy, and freshness.

## Exact model-artifact mismatch

- Manifest: `atlas/models/plausibility_v4_rf.manifest.json`
- Referenced path: `models/plausibility_v4_rf.pkl`
- Expected SHA-256:
  `96620b6de5f0467e4d68e66d55233aaab61110ff17c75057c1fc43ccf30d32fe`
- Actual SHA-256:
  `83361476a78590795c46a6197270c521529f1ddf50a440c7681d17773a0fdf85`

The logreg and regularized-RF model files matched their recorded artifact
digests when paths were resolved from the Atlas project root.

## Manifest failures in the A.M.Y system-paper release

Both manifests fail for the same 13 paths:

- five PDF figures;
- five SVG figures;
- `paper/amy_atlas_system_paper.md`;
- `paper/amy_atlas_system_paper.pdf`;
- `paper/amy_atlas_system_paper.tex`.

This pattern is consistent with post-manifest regeneration of paper/figure
artifacts. It does not establish malicious tampering; it establishes that those
release bytes no longer match the manifests.

## Positive controls

- Every one of the 1,653 historical provenance output files present at audit
  time matched its stored SHA-256.
- The 24-entry SSH disorder-study release manifest verified completely.
- Ed25519 signature generation and verification are real cryptographic
  operations, not mocked functions.

These controls are important: the paper should report working mechanisms as
clearly as defects.

## Commands used

The audit used read-only commands equivalent to:

```text
git rev-parse HEAD
git describe --tags --always --dirty
git status --porcelain=v1
git log -10 --format='%H %G?'
git verify-tag v1.0.0
shasum -a 256 <artifact>
(cd <release> && shasum -a 256 -c MANIFEST.sha256)
ollama --version
curl http://127.0.0.1:11434/api/version
```

The provenance count was produced by parsing each
`data/experiments/*/provenance.json`, reading the sibling `output.txt`, and
comparing a freshly computed SHA-256 with `tool.output_hash`.

Running `atlas/scripts/qa/verify_manifest_signatures.py` refreshed the ignored
diagnostic file `atlas/reports/manifest_signature_report.json`. It did not modify
tracked source.

Remote identity was checked with `git ls-remote origin`; local divergence was
checked with `git rev-list --left-right --count origin/main...HEAD`. No push,
release, tag, or remote mutation was performed.

## Relevant audited source SHA-256

```text
c33b35eadd317c018f5e68629a450138d5f2a3d1575b5d4d2a53f7bf269e3684  core/provenance.py
afcf529184c21d258750e5be949c1aaaa7f5ed39bc6d01007426a1dbae730750  core/security_hardening.py
ddc154b4eba15c0716a5df3b0aaa31541ec13234b2e56e314cf01b7c2bab72df  communication/paper_generator.py
fa9a777a4ae89355efb79511826399ae545057cfdde941cd8ba01590fc0d3a44  atlas/app/security/integrity_core.py
6f48ac52c96d2d0b10ad0445ac1f33d1f6b445a7f5d39467c4771808d1ce6077  atlas/app/validation/blockchain_validation.py
eeb0d423c39bb883c7141ca350bc78de64d5445052fdbe225317823f944f8c19  atlas/scripts/tools/sign_manifest.py
4816c5dec5553e983eda8832993a45a7cdd1acf69a9f1b4223c6ed3feee50164  atlas/scripts/qa/verify_manifest_signatures.py
fcaea7d4886b259c80eadc59da160053c214dabda41003526ae8f4854f8fe958  atlas/scripts/qa/validate_manifests.py
ffdf33d7e1683d7c44e3cdc5c61f6bdb586fb76c506efc742147785352902792  atlas/scripts/qa/validate_artifact_manifest.py
437f227a76832cc9db1ee596a3e4d4abdcfc1e20eec26c2a92b1bc7739647a93  atlas/.gitignore
c6c0c7a86fabdd3fd1a2eda1ee64cb2008920e7abb6b07eccc283dadb86546bf  pyproject.toml
7506c12b050262adab75b9da36b9ef062dd027c9f7cada01fa525b15d09adc79  amy.py
f659ce86e3be1f1d91ac0fa7237b852e55b3e7a3d0fcdae156c3e2851ea9d170  atlas/pyproject.toml
```

## Audit limitations

- No claim is made that the current working tree represents a public release.
- No secret value or private-key content was inspected or copied.
- Signature ownership was not externally established; only cryptographic
  validity under locally available public keys was tested.
- Historical data provenance beyond current file consistency was not inferred.
- The audit did not prove exploitability by a remote attacker.
