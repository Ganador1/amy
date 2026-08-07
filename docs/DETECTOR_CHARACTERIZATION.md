# Detector characterization contract

Automated checks can identify problems without being perfectly sensitive or
specific. A source hash identifies the implementation that ran; it does not
measure that implementation's capability. A.M.Y therefore records detector
identity, characterization, and verification as separate facts.

The local contract is `amy.detector-characterization.v2`. It is an A.M.Y
application contract, not an adopted in-toto predicate or standard. It follows
the boundary developed in in-toto/attestation#565: characterization evidence
stays separate and is referenced by digest rather than absorbed into an
evaluation-result claim.

## States and absence

- `measured`: a digest-bound evaluation set, class definitions, threshold,
  confusion matrix, estimates, confidence intervals, scope, limitations, and
  evidence reference are present and internally consistent.
- `unmeasured`: detector identity is known but no sufficient capability study
  exists. No sensitivity or specificity values are synthesized.
- `invalid`: a derived validation state. The supplied record is malformed or
  internally inconsistent and is not usable as evidence.

Unless a field says otherwise, absence means only that no claim is made. A
consumer must not infer or synthesize a default value. In particular, absence
is never sensitivity or specificity equal to one, and an empty inventory is
not a successful characterization.

## Measured record

Values used in policy comparisons are decimal strings, never JSON floats.
Artifact references use the in-toto `DigestSet` shape.

```json
{
  "schema_version": "amy.detector-characterization.v2",
  "status": "measured",
  "detector": {
    "name": "example_gate",
    "version": "1.2.3",
    "digest": {"sha256": "<64 lowercase hex characters>"}
  },
  "purpose": "safety",
  "task": {
    "positive_class": "unsafe output",
    "negative_class": "allowed output",
    "decision_threshold": "0.5",
    "scope": "held-out English prompts from benchmark v1"
  },
  "evaluation_set": {
    "digest": {"sha256": "<64 lowercase hex characters>"},
    "sample_size": 200,
    "positives": 100,
    "negatives": 100
  },
  "confusion_matrix": {"tp": 92, "fp": 10, "tn": 90, "fn": 8},
  "estimates": {
    "sensitivity": {"value": "0.92", "ci95_lower": "0.85", "ci95_upper": "0.96"},
    "specificity": {"value": "0.90", "ci95_lower": "0.82", "ci95_upper": "0.94"}
  },
  "asserted_assurance_level": "third_party",
  "evidence_ref": {
    "predicate_type": "https://example.org/DetectorCharacterization/v2",
    "digest": {"sha256": "<64 lowercase hex characters>"}
  },
  "limitations": ["The estimate is not portable beyond the declared scope."]
}
```

The validator recomputes sensitivity and specificity from the confusion matrix
and checks class totals, sample size, probability bounds, confidence-interval
ordering, digests, asserted assurance, evidence reference, and limitations.
Decimal estimates may differ from the exact ratio by at most `1e-12`.

## Assurance verification

`asserted_assurance_level` is producer testimony. The string `third_party`,
`reproduced`, or `enclave_attested` does not independently establish anything.
Safety and automatic external release require a separate verifier result:

```json
{
  "status": "verified",
  "signature_verified": true,
  "authorized_issuer": true,
  "verifier": {"id": "https://example.org/independent-verifier/v1"},
  "evidence_ref": {
    "predicate_type": "https://example.org/DetectorCharacterization/v2",
    "digest": {"sha256": "<same referenced evidence digest>"}
  },
  "verification_result_digest": {"sha256": "<verification result digest>"}
}
```

The policy checks exact reference equality, signature verification, issuer
authorization, verifier identity, and a digest over the verification result.
Authenticity, authorization, freshness, and rollback protection remain inputs
from their respective verification systems; this contract does not invent
them.

## Policy and asymmetric risk

The non-claim is symmetric—the harness is not proven fit for purpose—but the
consequence of under-detection depends on claim semantics:

- For a capability claim (“the model achieves X”), under-detection generally
  understates capability. The error is conservative, but the claim remains
  qualified to the declared scope.
- For a safety claim (“the model refuses X”), under-detection can yield a
  portable `passed: true` while the unsafe behavior occurred. Missing,
  unverified, or below-threshold characterization therefore blocks.

| Consumer | Unmeasured or absent | Invalid | Merely asserted assurance | Separately verified assurance |
|---|---|---|---|---|
| Safety decision | Block | Block | Block | Allow only if explicit lower confidence bounds pass |
| Scientific publication | Manual review; no automatic external release | Block | Manual review | Eligible only if explicit lower confidence bounds pass |
| Capability statement | Qualify | Block | Qualify to declared scope | Qualify to declared scope |

Detector characterization is necessary but not sufficient for scientific
validation. Dataset validity, independence, authorization, freshness,
reproducibility, and truth remain separate properties.

## Migration from v1

Version 2 deliberately rejects v1 records instead of silently reinterpreting
them. Migrate as follows:

- replace bare `sha256` members with `digest: {"sha256": "..."}`;
- encode thresholds, estimates, and confidence bounds as decimal strings;
- rename `assurance_level` to `asserted_assurance_level`;
- provide a separate assurance-verification result when policy needs
  independent assurance.

## Publication integration

`PaperGenerator` inventories the citation verifier, numeric verifier,
prepublication gate, and Reflection Agent; it also includes the peer reviewer
when enhancement invokes it. Until digest-bound benchmarks are supplied, each
is emitted as `unmeasured`. Generated local artifacts retain their existing
`publication_status`, but additionally report:

- `detector_assurance`
- `external_release_eligible`
- `manual_review_required`

The same summary is embedded in Markdown, PDF, and LaTeX so format conversion
cannot silently discard the limitation.
