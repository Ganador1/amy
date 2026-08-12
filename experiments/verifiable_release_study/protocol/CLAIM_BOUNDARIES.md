# Claim Boundaries

Version: `0.3.0-draft`

## Evidence labels

Every substantive manuscript claim must receive one of these labels in the
claim-evidence ledger:

- `OBSERVED`: directly measured in retained raw data.
- `REPRODUCED`: independently obtained under the declared reproduction rule.
- `SPECIFIED`: required by a frozen protocol or standard, not yet demonstrated.
- `TESTED`: exercised by a named test corpus with exact results.
- `INFERRED`: interpretation derived from evidence; assumptions are stated.
- `EXTERNAL`: supported by a cited primary source.
- `UNKNOWN`: not established and not assertable as fact.

## Forbidden shortcuts

| Avoid | Permitted only when |
|---|---|
| “immutable” | The text says *which bytes are immutable in which archive*; otherwise use “tamper-evident” |
| “blockchain-validated” | A real named distributed consensus system and independently checkable transaction are used |
| “cryptographically verified” | Digest, signature, subject binding, and trust policy all passed; name the scope |
| “authorized policy” | Exact policy bytes matched the expected SHA-256 from the identified external R0/deposit record, and its exact schemas were hash-bound |
| “signature proves correctness” | Never; signatures authenticate signed bytes/identity, not scientific truth |
| “100% reproducible” | Never as an unrestricted claim; state environments, tolerance, attempts, and result |
| “model version was fixed” | Weights or an immutable provider artifact are independently identified; a cloud label alone is insufficient |
| “independently validated” | The verifier/reproducer is outside the authoring code path and trust boundary |
| “all attacks” | The text says “all attacks in the frozen catalog” and provides that catalog |
| “no hallucinations” | Claims are instead traceable, checked, and assigned explicit uncertainty/status |
| “validator signatures” | Actual signatures and public trust roots are released and verified |

## Required manuscript language

- Hash result: “The recomputed SHA-256 matched the expected digest for X/Y
  listed artifacts.”
- Signature result: “The signature over the specified subject bytes was valid
  under key/certificate X; policy Y accepted/rejected the signer identity.”
- Policy result: “The verifier used exact policy bytes X after matching the
  expected SHA-256 from R0 record Y; the result also records the exact policy
  and terminal-result schema digests.” Merely reporting a newly observed policy
  hash is not authorization.
- Attestation result: “The attestation bound subject digest X to the standard
  workflow, builder, and source dependency in record Y; authenticated manifest
  X separately contained workflow-authored source/clean/tree/snapshot/lock/image
  assertions checked by P3.” This wording must not imply that the opaque source
  tar was semantically reconstructed into the declared Git tree. A syntactically
  valid USTAR fixture does not change that boundary.
- Reproduction result: “A clean environment obtained result X within tolerance
  T using the released artifacts.”
- Cloud model limitation: “The provider label and raw exchange were recorded,
  but undisclosed weights and serving infrastructure were not independently
  reproducible.”
- Negative result: report it with the same precision and artifact link as a
  favorable result.

## Claim-to-evidence rule

A claim may enter the abstract or conclusion only if:

1. its exact wording appears in `evidence/CLAIM_EVIDENCE_MATRIX.csv`;
2. all cited local artifacts are in the release manifest;
3. every numerical value is generated from released case-level data;
4. external factual claims cite primary sources;
5. limitations and attack scope are adjacent or unambiguously referenced;
6. an independent final audit did not mark it `UNSUPPORTED`.

The manuscript must preserve a visible distinction between exploratory audit
findings, preregistered confirmatory outcomes, post hoc analyses, and normative
recommendations.
