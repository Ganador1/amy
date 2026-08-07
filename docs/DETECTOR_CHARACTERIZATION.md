# Detector characterization contract

Automated checks can identify problems without being perfectly sensitive or
specific. A source hash identifies the implementation that ran; it does not
measure that implementation's capability. A.M.Y therefore records detector
identity and detector characterization as separate facts.

The local contract is `amy.detector-characterization.v1`. It is an A.M.Y
application contract, not an adopted in-toto predicate or standard.

## States

- `measured`: a digest-bound evaluation set, class definitions, threshold,
  confusion matrix, estimates, confidence intervals, scope, limitations, and
  evidence reference are present and internally consistent.
- `unmeasured`: detector identity is known but no sufficient capability study
  exists. No sensitivity or specificity values are synthesized.
- `invalid`: a derived validation state. The supplied record is malformed or
  internally inconsistent and is not usable as evidence.

Absence is never interpreted as sensitivity or specificity equal to one. An
empty detector inventory is likewise not a successful characterization.

## Measured record

```json
{
  "schema_version": "amy.detector-characterization.v1",
  "status": "measured",
  "detector": {
    "name": "example_gate",
    "version": "1.2.3",
    "sha256": "<64 lowercase hex characters>"
  },
  "purpose": "safety",
  "task": {
    "positive_class": "unsafe output",
    "negative_class": "allowed output",
    "decision_threshold": 0.5,
    "scope": "held-out English prompts from benchmark v1"
  },
  "evaluation_set": {
    "sha256": "<64 lowercase hex characters>",
    "sample_size": 200,
    "positives": 100,
    "negatives": 100
  },
  "confusion_matrix": {"tp": 92, "fp": 10, "tn": 90, "fn": 8},
  "estimates": {
    "sensitivity": {"value": 0.92, "ci95_lower": 0.85, "ci95_upper": 0.96},
    "specificity": {"value": 0.90, "ci95_lower": 0.82, "ci95_upper": 0.94}
  },
  "assurance_level": "third_party",
  "evidence_ref": {
    "predicate_type": "https://example.org/DetectorCharacterization/v1",
    "sha256": "<64 lowercase hex characters>"
  },
  "limitations": ["The estimate is not portable beyond the declared scope."]
}
```

The validator recomputes sensitivity and specificity from the confusion matrix
and checks class totals, sample size, probability bounds, confidence-interval
ordering, digests, assurance level, evidence reference, and limitations. The
record cannot establish that the referenced evidence is authentic merely by
naming it; signature and authorization checks remain separate policy inputs.

## Policy

| Consumer | Unmeasured or absent | Invalid | Valid, self-attested | Valid, third-party/reproduced |
|---|---|---|---|---|
| Safety decision | Block | Block | Block | Allow only if configured lower confidence bounds pass |
| Scientific publication | Require manual review; no automatic external release | Block | Require manual review | Eligible only when explicit lower-bound thresholds also pass |
| Capability statement | Qualify the claim | Block | Qualify to declared scope | Qualify to declared scope |

Detector characterization is necessary but not sufficient for scientific
validation. Dataset validity, independence, authorization, freshness,
reproducibility, and truth remain separate properties.

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
