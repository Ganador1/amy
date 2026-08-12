# Latest A.M.Y, ATLAS, and AXIOM Manuscripts: Code, Data, PDF, and Reference Audit

Date: 2026-07-13  
Classification: exploratory, same-host, current-byte audit  
Machine record: `LATEST_MANUSCRIPTS_DEEP_AUDIT_RAW_2026-07-13.json`  
Replay record: `LATEST_MANUSCRIPTS_DEEP_AUDIT_VALIDATION_2026-07-13.json`

## Decision

None of the five legacy manuscript families audited here is admissible as
positive scientific evidence for the new paper. They may be retained and cited
as bounded project history or as negative evidence about provenance and
publication controls. They must not supply confirmatory outcomes, performance
estimates, novelty claims, production-readiness claims, or independent
replication claims.

This decision does **not** assert that every stored number is false. It separates
five questions that the current manuscripts often collapse:

1. Do the cited bytes exist now?
2. Do their current SHA-256 digests match stored digests?
3. Is their producer, source revision, environment, and dependency graph fixed?
4. Is their origin authenticated by an authorized identity and trusted time?
5. Does the evidence support the scientific interpretation?

Several artifacts pass question 2. None thereby passes questions 3–5.

## Audited scope

| Family | Principal manuscript | Current SHA-256 | Disposition |
|---|---|---|---|
| Revised A.M.Y replication benchmark | `output/revised_papers/AMY_replication_benchmark_revised_20260501.md` | `4eb6bdc5bcd63b749f6494ea9a43a1456590e644060d949d190220b994cd21e6` | Historical, present-byte consistency only |
| ATLAS system paper | `atlas/docs/guides/ATLAS_SCIENTIFIC_PAPER.md` | `60941f0c24710d577f7ec6c8733f14b5591a537c553ac28a4d664e92cff4c3dd` | Unsupported positive validation |
| AXIOM META4 paper | `atlas/docs/guides/scientific_paper_latest.md` | `0595999491ef5ba37018bee668c8f0e3d2978cdcad20797836216eb26dabe1c0` | Incomplete template |
| Latest A.M.Y DNA paper | `papers/Computational_Analysis_of_DNA_Sequence_and_Protein_Analysis_20260706_183330.md` | `2faf646d13936a9b941427da0ff13740901431ac7984fb7004fef49ea533af17` | Requires reconstruction from source evidence |
| Atlas bond-energy paper | `experiments/novelty_hunt/papers/Empirical_Audit_of_Internal_Consistency_in_the_Atlas_Bond-En_20260521_201647.md` | `fad453133390596a4bc4b4aa9efc84b89f3a1706ee30faab8f3e65a4f6cc48b2` | Lookup-table demonstration, not chemistry validation |

The formal A.M.Y/Atlas system paper in `.worktrees/amy-system-paper` was audited
separately for code, data, statistics, release integrity, and PDF quality. This
report adds a primary-source check of its 14-entry bibliography.

The scanner did not import project code, execute a scientific tool, contact a
model or provider, read private-key bytes, or alter any audited manuscript.

## Findings

### LM01–LM02 — The revised A.M.Y benchmark has consistent bytes but an ambiguous corpus

The source manuscript enumerates 24 exact provenance paths. All 24 records are
present; all 24 output previews and all 24 separate `output.txt` files match the
declared SHA-256 and length. This supports only current-byte consistency.

The revised manuscript names eight representative paths and says that the
complete set of 24 can be enumerated by the `replication_` prefix. In the
current repository that prefix selects 96 provenance records. The intended 24
can be recovered only by consulting the older source manuscript. A future
release must use a closed manifest of exact paths and digests, never a mutable
filename prefix as the study denominator.

Across the intended 24 records:

| Field/property | Records |
|---|---:|
| Current preview SHA-256 matches declaration | 24/24 |
| Current `output.txt` SHA-256 matches declaration | 24/24 |
| Environment object present | 24/24 |
| Authenticated signature/attestation field | 0/24 |
| Source revision field | 0/24 |
| Exact dependency/container identity | 0/24 |
| Seed field | 0/24 |

The paper therefore cannot establish the historical executable bytes, exact
dependency state, authorized publisher, trusted production time, or independent
reproduction of those 24 outputs.

### LM03 — The ATLAS paper's headline results have no retained result object

The manuscript claims 3/3 successful workflows, 23.17 seconds total duration,
7.77 workflows per minute, and production readiness. No candidate
machine-readable result artifact was found. The linked integration source:

- contains three literal `success: True` outcomes;
- contains hard-coded/default `0.85` quality values;
- derives throughput from elapsed wall time;
- does not write a machine-readable result; and
- accompanies a manuscript whose references section is an explicit placeholder.

Source literals are not retained execution outcomes. None of those claims may
enter a scientific result table.

### LM04 — The AXIOM META4 paper is an unfinished template

`scientific_paper_latest.md` and both timestamped copies are byte-identical.
Each has SHA-256 `0595999491ef...` and contains eleven explicit appendix
placeholders. The cited `atlas/meta4_validation_results.json` contains 18 status
strings (`Imported`, `OK`, or `All services instantiated`) and none of the seven
model scores printed in the manuscript (`0.581`, `0.578`, `0.559`, `0.111`,
`0.933`, `0.944`, `0.878`).

The JSON may support a narrow import/smoke-test observation. It cannot support
the manuscript's evaluation scores, statistical conclusions, or system claims.

### LM05, LM10, LM11 — The newest DNA manuscript loses its own audit trail

The three cited provenance records and their `output.txt` files currently match
their stored SHA-256. None has authentication, source revision, dependency
identity, or seed. Four artifacts declared by the paper are absent:

- `manifest.json`;
- `numeric_tool_results.csv`;
- `numeric_tool_results.json`; and
- `literature_novelty_audit.json`.

The missing novelty record is consequential. The three named related works do
resolve to publisher records, but their existence does not recover the search
corpus, query, retrieval date, candidate set, title-overlap computation, or
ranking. The novelty boundary is therefore not replayable.

The paper also claims agreement between two GC measurements. Their retained
inputs are not the same biological object: E2 receives
`summary:[0.25,0.25,0.25,0.25]`, while E3 receives the 20-base sequence
`GCGCGCGCGCGCGCGCGCGC`. Similar-looking output numbers cannot be interpreted as
independent corroboration when the input and measured quantity are not bound.

The Markdown contains one leaked `</think>` tag and repeats its discussion
anchor twice. Its claims of MPS acceleration, machine-epsilon verification,
independent-hardware replication, and methodologically distinct corroboration
are not supported by the three provenance records.

#### Rendered PDF review

The six-page A4 PDF reviewed here has SHA-256
`b0cf19040da47d2635035237833219fe8be365de175804f6bd9742c69bd64d7f`.
It was inspected as rendered pages and with `pdfinfo`, `pdffonts`, and
`pdftotext`. No page clipping was observed, but it is not content-equivalent to
the Markdown and is not publication-ready:

- title metadata is anonymous, the PDF is untagged, and none of its five fonts
  is embedded;
- the `</think>` reasoning tag is visibly printed;
- `## Testable Predictions` is printed as literal Markdown;
- long artifact paths break awkwardly across lines;
- the machine-epsilon notation contains missing-glyph symbols; and
- the PDF omits Acknowledgments, Data Availability, and the complete Provenance
  Watermark, including the experiment IDs and output digests.

The omitted sections are not cosmetic: they are the manuscript's disclosure
and traceability layer. PDF and source must be compared semantically and
visually before release, then both formats must be included in the signed
manifest.

### LM06 — The bond-energy paper measures a lookup table, not chemistry

All eight cited outputs and separate output files match their stored SHA-256.
The producer creates experiment IDs with a truncated six-hex-character MD5,
uses SHA-256 for output bytes, and invokes a tool implemented as a literal bond
energy dictionary. Its records have no environment, provenance version,
authentication, source revision, dependency identity, or seed.

The manuscript says both that it uses eight computational methods and that it
uses a single tool. It discusses unmeasured HOMO–LUMO behavior and claims MPS,
machine-epsilon, and execution-environment controls absent from the records.
The defensible description is: **eight deterministic queries against a
source-embedded reference table**. It is not an empirical validation of bond
energies and does not estimate model accuracy.

### LM07–LM09 — Bibliography completeness is not metadata or design validity

All 14 citation keys in the formal paper resolve to bibliography entries and
all 14 entries are cited. Eight entries are arXiv preprints. One current
metadata error was observed: local `wang2026provenance` adds “A Survey of” to
the title and gives an author list different from the current official
arXiv:2606.04990 record. The entry must be refreshed from the immutable version
actually cited, with that version and retrieval date recorded.

The revised A.M.Y benchmark cites Stodden et al. as 2014 while the official
Science record is 2016, volume 354, issue 6317, pages 1240–1241,
doi:10.1126/science.aah6168. The volume/issue already corresponds to 2016, so
the local citation is internally inconsistent.

McNemar, bootstrap, and Holm are appropriate general method references. They do
not establish that repeated case-seed rows in this particular benchmark are
independent experimental units. Nosek et al. supports preregistration as a
practice; it does not convert an unsigned local Git record into a trusted public
registration. Citation presence must never be used to supply missing design
evidence.

## Primary reference checks

| Local use | Official record checked | Result |
|---|---|---|
| Revised A.M.Y references | Baker DOI `10.1038/533452a`; OSC DOI `10.1126/science.aac4716`; Stodden DOI `10.1126/science.aah6168`; NumPy DOI `10.1038/s41586-020-2649-2` | Stodden year mismatch; no discrepancy observed for the other three fields checked |
| Formal provenance survey | `https://arxiv.org/abs/2606.04990` | Current title and author list differ from local BibTeX |
| DNA closest-literature signals | DOIs `10.1093/bioinformatics/btaf222`, `10.1093/nar/gkag608`, `10.1016/j.compbiolchem.2026.109217` | Works exist; unretained novelty procedure remains unverifiable |
| Formal statistical methods | McNemar, Efron bootstrap, Holm primary records | General methods only; no support for this dataset's independence assumptions |

The exact URLs used by the curated 2026-07-13 reference snapshot are retained
inside the machine-readable audit. External pages can change; the future paper
must archive versioned metadata records or content digests where licensing
permits.

## Admissibility for the new paper

Permitted:

- report that current cited output bytes match stored unsigned SHA-256 values;
- describe the observed provenance gaps and internal contradictions;
- use these failures to motivate the preregistered release-verification study;
- retain legacy manuscripts unchanged as historical artifacts.

Not permitted:

- pool legacy executions into a confirmatory denominator;
- call a digest match authentication, independent reproduction, or truth;
- repeat ATLAS/AXIOM success, score, throughput, or readiness claims;
- describe the DNA literature list as a replayed novelty search;
- describe the bond-energy lookup table as empirical chemistry; or
- silently repair a previously identified release in place.

## Required remediation

1. Build the new manuscript only from a frozen case registry and exact evidence
   manifest; do not inherit legacy outcomes.
2. Bind every result to source commit plus exported-source SHA-256, dependency
   lock/container digest, complete inputs, command, environment, seed, outputs,
   and error logs.
3. Authenticate the release manifest and provenance under a frozen identity,
   trust-root, predicate, and transparency policy.
4. Preserve exact model request/response bytes and effective parameters while
   labeling provider-opaque model identity as a limitation.
5. Freeze the analysis implementation and tests before confirmatory data.
6. Use a trusted, read-only, time-stamped preregistration and retain its public
   identifier.
7. Validate every bibliography entry against a primary/versioned record and
   distinguish preprints from peer-reviewed versions.
8. Require independent domain and artifact review; model reviews remain
   advisory.
9. Render and compare every publication format, including metadata, fonts,
   accessibility, figures, equations, disclosures, and complete content.
10. Publish corrections as new authenticated versions with new version DOI and
    digests; preserve superseded bytes and the reason for change.

## Reproduction

From `experiments/verifiable_release_study`:

```bash
uv run --frozen python scripts/audit_latest_manuscripts.py \
  --output audit/LATEST_MANUSCRIPTS_DEEP_AUDIT_RAW_2026-07-13.json
uv run --frozen python scripts/validate_latest_manuscripts_audit.py \
  --output audit/LATEST_MANUSCRIPTS_DEEP_AUDIT_VALIDATION_2026-07-13.json
uv run --frozen pytest -q tests/test_latest_manuscripts_audit.py
```

The retained replay is valid and reports:

- scanner SHA-256:
  `7f10dd0ed2657fdd3b53a53834b8afb6de86f01a85a622b046f25ae5f978eac3`;
- pretty JSON SHA-256:
  `f7121f209496bf9dc646d625663b523f7c573eabaab850d478269f44d1f9e245`;
- retained and fresh canonical SHA-256:
  `333e3cc70c5fb7550cefa680af8a842480708b009044d2711c579f3c181c995b`;
- two audit tests passed.

## Boundaries

This is a current-snapshot audit, not a reconstruction of author intent or a
historical environment. It does not execute the scientific producers, decide
whether any biological or chemical value is externally true, establish
malicious alteration, or constitute independent replication. External metadata
comparisons are a curated 2026-07-13 snapshot. The PDF review applies only to
the exact digest printed above. Same-environment canonical replay validates the
scanner's deterministic accounting, not authorship, scientific truth, or
independence.
