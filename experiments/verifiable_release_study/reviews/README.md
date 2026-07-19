# Exploratory Protocol Reviews

Reviews in this directory are advisory and pre-registration. They may reveal
ambiguous policy, missing attacks, or unsupported claims. They are not
confirmatory observations and do not define benchmark ground truth.

The current frozen design is `protocol/MODEL_REVIEW_PROTOCOL.json`. It binds ten
distinct role/model slots to 49 exact source files across implementation, tests,
schemas, audits, protocol, and paper-facing claim controls. It requires one
parallel attempt per slot, no retry or replacement within a batch, no voting,
and a closed JSON response. Provider labels do not identify immutable weights.

Validate request construction without network access from the study root:

```text
python scripts/run_model_review_batch.py --validate-only
```

Execute a new batch only from an environment permitted to reach the Ollama
endpoint:

```text
python scripts/run_model_review_batch.py --endpoint http://127.0.0.1:11434
```

The retained `model_review_20260713T225218Z` batch is a complete failed attempt
set: all ten concurrent loopback calls ended with `Operation not permitted`, so
there are zero HTTP successes, zero closed responses, and zero findings. Its
canonical validation is `model_review_20260713T225218Z/VALIDATION.jcs.json`.
Any later execution creates a new batch and must not replace this evidence.

The older `run_protocol_review.py` batches remain historical exploratory
records; they do not satisfy the current frozen design.

Each batch stores:

- the exact source-file digests supplied to reviewers;
- exact HTTP request and response bytes;
- observable Ollama client/server metadata;
- timestamps, duration, HTTP/error status, and response SHA-256;
- a summary that includes unavailable, retired, blank, and malformed responses.

No response should be silently dropped. Proposed changes enter the protocol only
after independent source/code review and are documented in a synthesis record.
