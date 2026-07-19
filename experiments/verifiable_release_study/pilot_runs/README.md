# Exploratory Synthetic Pilot Ledger

All runs in this directory are excluded from confirmatory denominators. Raw run
trees are held in local custody outside source Git because the adversarial
fixtures include FIFO filesystem objects. A new run directory is created for
every attempt; prior bytes are never overwritten. The committed, bounded record
of the two retained runs is `PILOT_RETENTION_SUMMARY_2026-07-18.json`; it binds
tree hashes, member counts, byte counts, and aggregate outcomes without claiming
independent reproduction.

## `pilot_20260713T054657Z`

- Protocol/catalog: `0.3.0-draft`
- Implementation: `0.3.0.dev0`
- Purpose: first retained full 34 × 4 execution after the protocol-version bump.
- Outcome: 136 terminal results, zero profile-contract mismatches, zero clean
  failures, zero `ERROR` decisions.
- Limitation: predates the standalone contract ledger and pilot-run validator.
  It remains historical evidence and is not the preferred validation run.

## `pilot_20260713T054931Z`

- Protocol/catalog: `0.3.0-draft`
- Implementation: `0.3.1.dev0`
- Purpose: full run with archived contracts and independent post-run hash/schema
  validation.
- Validator result: valid; 34 cases, 136 results, zero profile-contract
  mismatches, zero clean failures, no validator errors or warnings.
- The 34 deterministic case archives are byte-identical to those from
  `pilot_20260713T054657Z` in the same macOS environment.
- This is evidence of same-environment generator determinism only. It is not an
  independent reproduction and does not validate production Sigstore behavior.

When the separately retained raw tree is available, its preferred local
validation command is:

```bash
experiments/verifiable_release_study/.venv/bin/python \
  experiments/verifiable_release_study/scripts/validate_pilot_run.py \
  experiments/verifiable_release_study/pilot_runs/pilot_20260713T054931Z
```

This command is intentionally unavailable in a source-only clone. The absence
of the local raw tree must not be interpreted as a successful validation.
