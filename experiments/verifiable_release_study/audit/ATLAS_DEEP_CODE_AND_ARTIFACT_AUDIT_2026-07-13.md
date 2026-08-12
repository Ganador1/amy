# ATLAS Deep Code and Artifact Audit — 2026-07-13

Status: **exploratory, pre-registration, read-only**  
Snapshot commit: `40663854cfc2a2cf8e8e828cc0ac7c031db58963`  
Snapshot description: `v1.0.0-68-g4066385-dirty`  
Paper-use status: context and defect discovery only; not confirmatory evidence

## Conclusion first

ATLAS currently contains real Ed25519 signing code and three signatures that are
cryptographically valid under a locally available public key. That positive
result does **not** establish a verifiable release chain. At the audited byte
snapshot:

| Check | Result |
|---|---:|
| Manifest signatures valid under the local key | 3/3 |
| Referenced model files matching their declared SHA-256 | 2/3 |
| Stored manifest self-hashes matching validator 1 | 0/3 |
| Stored manifest self-hashes matching validator 2 | 0/3 |
| Declared manifest Git revisions resolving to commits | 0/3 |
| Publication packages with a stored package hash | 9/13 |
| Stored package hashes matching current package bytes | 0/9 |

The evidence therefore supports the narrow statement “three manifest
signatures verify under one local key.” It refutes broader statements that the
current model artifacts, package bytes, scientific results, or a public chain
of custody have thereby been verified.

## Evidence artifacts and replay

The audit is backed by:

- executable scanner: `scripts/audit_atlas_integrity.py`;
- retained raw result: `audit/ATLAS_DEEP_AUDIT_RAW_2026-07-13.json`;
- scanner SHA-256:
  `de47d4ec01aab23f5e14174208314084da820f9061b3f0737995e4213cb32799`;
- raw-result SHA-256:
  `949e1a5fb40fd85cc0267073d0b40eaa0832282f61ea481010e69a5f27abd8a7`.

Replay from the study directory:

```bash
uv run --frozen --extra pilot python scripts/audit_atlas_integrity.py --compact
```

The scanner imports no ATLAS module, reads no private-key bytes, deserializes no
pickle/joblib object, and writes nothing. It hashes files, parses JSON, verifies
Ed25519 signatures with public keys, reproduces the package-hash algorithm, and
performs a bounded static source scan. Its raw output records source-file hashes
for the code on which the principal findings depend.

## 1. Signed manifest and present model are different trust questions

The manifest `atlas/models/plausibility_v4_rf.manifest.json` declares:

```text
expected SHA-256  96620b6de5f0467e4d68e66d55233aaab61110ff17c75057c1fc43ccf30d32fe
expected bytes    1334275
```

The present model file has:

```text
actual SHA-256    83361476a78590795c46a6197270c521529f1ddf50a440c7681d17773a0fdf85
actual bytes      1334275
```

Equal size does not repair the digest mismatch. The signature remains valid
because it authenticates the old digest in the manifest, not the bytes now at
the referenced path.

The version ledger supplies a plausible, directly observed sequence:

| Time | Recorded model digest | Tag |
|---|---|---|
| `2025-09-17T07:32:06.984713` | `96620b6d…d32fe` | `update_dataset.py` |
| `2025-09-17T07:32:27.623056` | `83361476…fdf85` | `train_plausibility_model_v4.py` |

This is consistent with replacement of the model roughly 20.6 seconds after
the earlier record without regenerating and re-signing the manifest. That is an
inference from the retained ledger, not proof of the historical process that
produced the files.

The manifest also declares `n_estimators=500`, whereas every syntactically
identified `RandomForestClassifier` construction in the associated training
script uses 200 or 300 estimators. Because the audit deliberately did not load
the pickle, this proves a discrepancy between manifest metadata and producer
source; it does not establish the internal parameter of the current object.

## 2. The signature primitive works, but public trust is absent

The signer and verifier use Ed25519 over deterministic JSON bytes with the
top-level `signatures` member removed. The raw audit independently verified all
three signatures against fingerprint:

```text
25c7a15472815b86addb077aa5797afa6785c4d096adfcbc43fb8d9fcd06d007
```

Positive conclusion: the signatures are not mocks and detect a change to the
signed manifest payload.

Trust and policy failures remain:

- all key material is ignored by Git, including the public key required to
  reproduce the local decision;
- the private key exists unencrypted at mode `0644`, so group/other users can
  read it; its content and digest were intentionally not collected;
- no externally authenticated signer identity, certificate, transparency-log
  entry, revocation policy, rotation history, or threshold policy was found;
- the fingerprint embedded in the signed object cannot bootstrap trust in its
  own signer;
- the verifier does not enforce the declared `alg` field;
- because the complete `signatures` member is outside the signed payload, a
  signature timestamp can be changed while the cryptographic verification
  remains valid. The scanner confirmed this for 3/3 entries.

Accordingly, “signed by an authorized ATLAS release identity at time T” is not
an allowed claim for these artifacts.

## 3. Both manifest validators fail as release gates

`atlas/scripts/qa/validate_manifests.py` computes
`manifest_hash_matches`, but its per-manifest `valid` value depends only on
schema errors. A self-hash mismatch therefore coexists with `valid=true`, and
the mismatch is not included in the strict exit decision.

`atlas/scripts/qa/validate_artifact_manifest.py` does try to validate artifacts,
but resolves a declared path such as `models/foo.pkl` relative to the directory
already named `models`. All three become `atlas/models/models/foo.pkl`, and none
exists. It also uses a different manifest self-hash representation.

The independent scanner reproduced both self-hash algorithms. Zero of three
stored self-hashes matched either algorithm. It also verified that all three
manifests declare `git_commit="0000000"`, which does not resolve to a commit.

This creates two opposite false signals:

- validator 1 can report structurally valid despite failed self-hash checks;
- validator 2 can report valid project-root artifacts as missing because of its
  base-path rule.

A paper must not count either tool's aggregate `valid` field without recomputing
the underlying checks.

## 4. Untrusted deserialization precedes integrity verification

The broad static scan covered 4,877 project Python files after excluding named
dependency, virtual-environment, cache, and `test_env` directories. It found 43
syntactic `pickle`/`joblib` load sites. This number is an inventory, not a count
of reachable vulnerabilities; archived, legacy, and inactive code remains in
the scanned universe.

Manual reachability review identified direct loads of the RF model in:

- `atlas/scripts/tools/eval_plausibility_model_v4.py`;
- `atlas/scripts/tools/compare_plausibility_models_v4.py`;
- `atlas/scripts/tools/pipeline_metadata_v4.py`.

These offline paths do not first enforce expected file SHA-256, a trusted
manifest signature, signer policy, or a frozen sklearn/joblib environment. A
separate meta-model path in
`atlas/improvements/advanced_plausibility_scorer.py` also loads a pickle if the
currently absent file appears. The active plausibility API was observed to use
a heuristic rather than this RF, so remote reachability of the audited RF was
not established.

The security consequence is bounded but serious: loading a pickle crosses an
arbitrary-code-execution trust boundary. The verifier must validate immutable
bytes and policy before any deserialization, ideally in a sandbox with a safer
artifact format.

## 5. Publication package hashes are circular and presently fail

The implementation documents its package digest as “BLAKE3” but instantiates
`hashlib.blake2b()`, which is BLAKE2b-512. The algorithm hashes each relative
path followed by file bytes in sorted order.

The generation sequence is self-invalidating:

1. hash the initial package;
2. write `integrity_proof.json` containing that hash;
3. recompute a later hash;
4. write `manifest.json` and `package_hash.txt` containing the later value;
5. verification hashes all files again, including those newly written files.

For the 13 retained publication directories:

- 9 contain a stored `package_hash.txt`;
- 0/9 stored hashes equal a fresh reproduction of the implementation hash;
- 9/9 manifests repeat the stored hash;
- 0/9 integrity proofs repeat the stored hash;
- 8 proofs assert `blockchain_validation=true` despite the package mismatch.

The result is not evidence of malicious modification. It is evidence that the
defined package construction has no stable non-self-referential digest and that
the stored validation flag does not establish current byte integrity.

## 6. “Blockchain” is not distributed validation

Code inspection of `atlas/app/validation/blockchain_validation.py` found a local
in-memory linked list with SHA-256 links and a bounded proof-of-work loop. It has
no peer network, persistence, validator key policy, distributed consensus, or
active signature verification. `validate_pinn_result` creates a block and then
sets `is_valid=True` and confidence `0.5`; the proof-of-work loop may stop after
50,000 attempts and the block is still appended. `is_chain_valid` checks only
recomputed current hashes and previous links.

This mechanism may be described as a local hash-linked audit simulation. It may
not be described as blockchain consensus, independent validation, or evidence
that a scientific claim is true. If an external append-only transparency anchor
is required, it needs a separately trusted service and an explicit threat
model; the retained GitHub/Sigstore/Rekor path is the current candidate for
release identity, not this local list.

## 7. Active CI does not enforce the ATLAS evidence chain

The root repository has three active workflow files. None mentions the manifest
signature verifier or the artifact-manifest validator. Four ATLAS workflows are
nested below `atlas/.github/workflows`; GitHub does not execute nested workflows
as workflows of the parent repository.

Thus the code containing signature, manifest, and Merkle checks is not currently
an active release gate for the audited parent repository. Even if moved, the
observed false-positive/false-negative validator defects must be corrected
before making it blocking.

## 8. Public wording exceeds observed evidence

The scanner retained four exact claim locations in generated publication
material, including statements that all results are cryptographically
verifiable, all artifacts and computational steps are signed, validation uses
distributed consensus, and all results were validated by the AXIOM blockchain.

These statements are contradicted by the byte and code evidence above. They
must be removed from the new manuscript, not softened in a footnote. Valid
signatures, valid content digests, authorized identity, complete provenance,
reproducible computation, and scientific validity are separate propositions.

## Allowed and forbidden paper claims at this snapshot

Allowed with the retained raw audit:

- three manifest signatures verified under the locally available Ed25519 key;
- two of three referenced model files matched their declared SHA-256;
- the signed RF manifest referenced a same-size model with a different SHA-256;
- neither implemented manifest self-hash representation matched any stored
  self-hash;
- no stored publication package hash matched current bytes under the audited
  implementation;
- the relevant release checks were absent from active root CI.

Forbidden unless new evidence is produced:

- “ATLAS artifacts are cryptographically verified” without a named finite set;
- “the signer is the authorized ATLAS author/release service”;
- “blockchain consensus independently validated the result”;
- “a valid signature proves the model bytes or scientific conclusion”;
- “the current package can be reproduced from a public clean clone”;
- “all model-loading paths validate integrity before deserialization.”

## Minimum repair sequence before any confirmatory use

1. Define one closed-world manifest with one canonical byte representation;
   avoid a self-hash, or hash a formally specified projection that excludes its
   digest field.
2. Regenerate the RF artifact deterministically, record a real full Git object
   ID and environment lock, then regenerate and attest the manifest only after
   final bytes exist.
3. Replace local self-declared keys with the frozen GitHub Actions/Sigstore
   release identity and an independently bootstrapped trusted root.
4. Make one verifier enforce subject bytes, signature, identity, transparency,
   source revision, clean build, builder, materials, paths, sizes, and payload
   digests before any model load.
5. Define a non-self-referential release archive and test positive and negative
   controls in active root CI using action commit OIDs rather than mutable tags.
6. Remove the blockchain and universal-verifiability wording. If the local
   linked list remains, name it accurately and exclude it from security claims.
7. Add clean-clone, tamper, key-substitution, stale-manifest, path, pickle, and
   time-of-check/time-of-use tests that fail closed.

## Limitations

- The working tree was dirty; commit identity alone does not identify all
  audited bytes. Relevant source SHA-256 values are retained in the raw result.
- Local possession or ownership of the private key was not investigated.
- The audit established no remote exploit path and executed no untrusted model.
- Static call counts do not prove reachability.
- Historical intent and causality were not inferred from timestamps alone.
- A cryptographically intact release would still not prove that a scientific
  interpretation is correct.
