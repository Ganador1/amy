#!/usr/bin/env python3
"""Deterministic, read-only audit of recent A.M.Y/Atlas/AXIOM manuscripts.

The scanner verifies present bytes, cited local artifacts, output digests, and
selected source-to-claim links.  It never imports project code, executes a
scientific tool, contacts a model/provider, or treats an unsigned digest as an
authenticated signature.  External bibliography expectations are a curated
snapshot whose primary-source URLs are retained in the output.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


STUDY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPOSITORY_ROOT = STUDY_ROOT.parents[1]
DEFAULT_PAPER_WORKTREE = DEFAULT_REPOSITORY_ROOT / ".worktrees/amy-system-paper"

AMY_REVISED = Path("output/revised_papers/AMY_replication_benchmark_revised_20260501.md")
AMY_REPLICATION_SOURCE = Path("papers/best/AMY_Replication_Study_20260501_174337.md")
AMY_DNA_STEM = Path("papers/Computational_Analysis_of_DNA_Sequence_and_Protein_Analysis_20260706_183330")
ATLAS_PAPER = Path("atlas/docs/guides/ATLAS_SCIENTIFIC_PAPER.md")
ATLAS_INTEGRATION_SOURCE = Path("atlas/tests/integration/test_ultimate_integration.py")
AXIOM_PAPERS = (
    Path("atlas/docs/guides/scientific_paper_latest.md"),
    Path("atlas/docs/guides/scientific_paper_axiom_meta4_20250911_131250.md"),
    Path("atlas/docs/guides/scientific_paper_axiom_meta4_20250911_131243.md"),
)
AXIOM_RESULT = Path("atlas/meta4_validation_results.json")
BOND_PAPER = Path(
    "experiments/novelty_hunt/papers/"
    "Empirical_Audit_of_Internal_Consistency_in_the_Atlas_Bond-En_20260521_201647.md"
)
BOND_PAPER_COPY = Path(
    "papers/Empirical_Audit_of_Internal_Consistency_in_the_Atlas_Bond-En_20260521_201647.md"
)
BOND_HUNT_SOURCE = Path("experiments/novelty_hunt/hunt.py")
ATLAS_TOOL_SOURCE = Path("atlas/app/run_agent_with_tools_legacy.py")

FORMAL_PAPER_REL = Path("experiments/amy_system_paper/release/paper")
FORMAL_MD = FORMAL_PAPER_REL / "amy_atlas_system_paper.md"
FORMAL_BIB = FORMAL_PAPER_REL / "references.bib"

AUTH_KEYS = {
    "signature",
    "signatures",
    "certificate",
    "certificates",
    "dsse",
    "sigstore",
    "rekor",
    "attestation",
    "authenticated",
}
REVISION_KEYS = {"git_commit", "git_sha", "source_revision", "revision", "commit"}
DEPENDENCY_KEYS = {
    "dependencies",
    "dependency_lock",
    "lockfile",
    "requirements_hash",
    "container_digest",
    "image_digest",
}
SEED_KEYS = {"seed", "random_seed", "rng_seed"}

OFFICIAL_REFERENCE_SOURCES = {
    "lu2024aiscientist": "https://arxiv.org/abs/2408.06292",
    "yamada2025aiscientistv2": "https://arxiv.org/abs/2504.08066",
    "gottweis2025coscientist": "https://arxiv.org/abs/2502.18864",
    "schmidgall2025agentlaboratory": "https://arxiv.org/abs/2501.04227",
    "chen2024scienceagentbench": "https://arxiv.org/abs/2410.05080",
    "liu2026sciagentarena": "https://arxiv.org/abs/2606.12736",
    "riosgarcia2026epistemic": "https://arxiv.org/abs/2604.18805",
    "wang2026provenance": "https://arxiv.org/abs/2606.04990",
    "soilandreyes2022rocrate": "https://doi.org/10.3233/DS-210053",
    "leo2024workflowrun": "https://doi.org/10.1371/journal.pone.0309210",
    "mcnemar1947correlated": "https://doi.org/10.1007/BF02295996",
    "efron1979bootstrap": "https://doi.org/10.1214/aos/1176344552",
    "holm1979multiple": "https://www.jstor.org/stable/4615733",
    "nosek2018preregistration": "https://pubmed.ncbi.nlm.nih.gov/29531091/",
}

AMY_REVISED_REFERENCE_SOURCES = {
    "baker2016reproducibility": "https://doi.org/10.1038/533452a",
    "openscience2015reproducibility": "https://doi.org/10.1126/science.aac4716",
    "stodden2016enhancing": "https://doi.org/10.1126/science.aah6168",
    "harris2020numpy": "https://doi.org/10.1038/s41586-020-2649-2",
}

DNA_CLOSEST_LITERATURE_SOURCES = {
    "neffy": "https://doi.org/10.1093/bioinformatics/btaf222",
    "caveat_emptor": "https://doi.org/10.1093/nar/gkag608",
    "ai_in_bioinformatics": "https://doi.org/10.1016/j.compbiolchem.2026.109217",
}

DNA_PDF_VISUALLY_REVIEWED_SHA256 = (
    "b0cf19040da47d2635035237833219fe8be365de175804f6bd9742c69bd64d7f"
)

WANG_CURRENT_TITLE = (
    "From Agent Traces to Trust: Evidence Tracing and Execution Provenance in LLM Agents"
)
WANG_CURRENT_AUTHORS = [
    "Yiqi Wang",
    "Jiaqi Zhang",
    "Taotao Cai",
    "Zirui Liu",
    "Qingqiang Sun",
    "Zequn Sun",
    "Zhangkai Wu",
    "Mingkai Zhang",
    "Yanming Zhu",
]


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def file_record(path: Path, root: Path) -> dict[str, Any]:
    return {
        "path": path.relative_to(root).as_posix(),
        "exists": path.is_file(),
        "size_bytes": path.stat().st_size if path.is_file() else None,
        "sha256": sha256(path) if path.is_file() else None,
    }


def all_mapping_keys(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            found.add(str(key).lower())
            found.update(all_mapping_keys(child))
    elif isinstance(value, list):
        for child in value:
            found.update(all_mapping_keys(child))
    return found


def provenance_record(path: Path, root: Path) -> dict[str, Any]:
    result: dict[str, Any] = file_record(path, root)
    if not path.is_file():
        return result
    value = json.loads(read_text(path))
    tool = value.get("tool") or {}
    preview = str(value.get("output_preview") or "")
    keys = all_mapping_keys(value)
    output_path = path.with_name("output.txt")
    result.update(
        {
            "experiment_id": value.get("experiment_id"),
            "tool_name": tool.get("name"),
            "tool_input": tool.get("input"),
            "declared_output_sha256": tool.get("output_hash"),
            "preview_sha256": sha256_bytes(preview.encode("utf-8")),
            "preview_matches_declared_output_sha256": (
                tool.get("output_hash") == sha256_bytes(preview.encode("utf-8"))
            ),
            "declared_output_length": tool.get("output_length"),
            "preview_character_length": len(preview),
            "preview_length_matches": tool.get("output_length") == len(preview),
            "separate_output_file": output_path.is_file(),
            "separate_output_sha256": sha256(output_path) if output_path.is_file() else None,
            "separate_output_matches_declared": (
                output_path.is_file() and sha256(output_path) == tool.get("output_hash")
            ),
            "environment_present": isinstance(value.get("environment"), dict),
            "provenance_version_present": bool(value.get("provenance_version")),
            "authentication_field_present": bool(keys & AUTH_KEYS),
            "source_revision_field_present": bool(keys & REVISION_KEYS),
            "dependency_identity_field_present": bool(keys & DEPENDENCY_KEYS),
            "seed_field_present": bool(keys & SEED_KEYS),
        }
    )
    return result


def summarize_provenance(records: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "records": len(records),
        "present": sum(bool(item.get("exists")) for item in records),
        "preview_hash_matches": sum(
            bool(item.get("preview_matches_declared_output_sha256")) for item in records
        ),
        "preview_length_matches": sum(bool(item.get("preview_length_matches")) for item in records),
        "separate_output_files": sum(bool(item.get("separate_output_file")) for item in records),
        "separate_output_hash_matches": sum(
            bool(item.get("separate_output_matches_declared")) for item in records
        ),
        "environment_present": sum(bool(item.get("environment_present")) for item in records),
        "provenance_version_present": sum(
            bool(item.get("provenance_version_present")) for item in records
        ),
        "authentication_fields": sum(
            bool(item.get("authentication_field_present")) for item in records
        ),
        "source_revision_fields": sum(
            bool(item.get("source_revision_field_present")) for item in records
        ),
        "dependency_identity_fields": sum(
            bool(item.get("dependency_identity_field_present")) for item in records
        ),
        "seed_fields": sum(bool(item.get("seed_field_present")) for item in records),
    }


def extract_backtick_paths(text: str, prefix: str) -> list[str]:
    # Do not pair raw backticks: fenced code blocks contain three backticks and
    # make a naive `...` regex span large, unrelated parts of a manuscript.
    # Every retained evidence/artifact path in this corpus uses this closed
    # portable character set.
    pattern = re.compile(re.escape(prefix) + r"[A-Za-z0-9_./=+\-]+")
    return sorted(set(pattern.findall(text)))


def audit_amy_revised(root: Path) -> dict[str, Any]:
    paper_path = root / AMY_REVISED
    source_path = root / AMY_REPLICATION_SOURCE
    paper = read_text(paper_path)
    source = read_text(source_path)
    source_data = source.split("## Data Availability", 1)[1].split("## References", 1)[0]
    exact_paths = extract_backtick_paths(source_data, "data/experiments/replication_")
    records = [provenance_record(root / path, root) for path in exact_paths]
    all_prefix_records = sorted(
        root.glob("data/experiments/replication_*/provenance.json")
    )
    representative_paths = extract_backtick_paths(
        paper.split("## 6. Reproducibility and data availability", 1)[1],
        "data/experiments/replication_",
    )
    family_counts = Counter(
        str((json.loads(read_text(root / path)).get("tool") or {}).get("name"))
        for path in exact_paths
    )
    return {
        "manuscript": file_record(paper_path, root),
        "source_manuscript": file_record(source_path, root),
        "declared_execution_count": 24,
        "exact_source_data_paths": exact_paths,
        "exact_source_data_path_count": len(exact_paths),
        "representative_paths_in_revision": representative_paths,
        "representative_path_count": len(representative_paths),
        "all_current_replication_prefix_records": len(all_prefix_records),
        "prefix_is_an_unambiguous_24_record_selector": len(all_prefix_records) == 24,
        "paper_claims_prefix_enumerates_complete_set": (
            "complete set of 24 records can be enumerated by the `replication_` prefix" in paper
        ),
        "tool_family_counts": dict(sorted(family_counts.items())),
        "provenance_summary": summarize_provenance(records),
        "records": records,
        "reference_audit": {
            "official_primary_source_urls": AMY_REVISED_REFERENCE_SOURCES,
            "stodden_local_citation": (
                "Stodden, V. et al. (2014). Enhancing reproducibility for "
                "computational methods. Science, 354(6317), 1240-1241."
            ),
            "stodden_current_official_metadata": {
                "year": 2016,
                "journal": "Science",
                "volume": "354",
                "issue": "6317",
                "pages": "1240-1241",
                "doi": "10.1126/science.aah6168",
            },
            "stodden_year_matches_official_record": False,
            "other_three_reference_metadata_discrepancies_observed": [],
        },
        "interpretation": {
            "present_byte_consistency_supported": all(
                item.get("preview_matches_declared_output_sha256") for item in records
            ),
            "publisher_or_origin_authentication_supported": False,
            "historical_code_identity_supported": False,
            "dependency_exact_replay_supported": False,
            "independent_replication_supported": False,
        },
    }


def audit_atlas_paper(root: Path) -> dict[str, Any]:
    paper_path = root / ATLAS_PAPER
    source_path = root / ATLAS_INTEGRATION_SOURCE
    paper = read_text(paper_path)
    source = read_text(source_path)
    preserved = [
        path.relative_to(root).as_posix()
        for path in root.glob("atlas/**/*ultimate*result*.json")
        if "cache/" not in path.as_posix()
    ]
    return {
        "manuscript": file_record(paper_path, root),
        "candidate_test_source": file_record(source_path, root),
        "claims": {
            "success_rate_3_of_3": "100% (3/3 workflows" in paper,
            "duration_23_17_seconds": "23.17 seconds" in paper,
            "throughput_7_77_per_minute": "7.77 complete workflows per minute" in paper,
            "production_ready": "Production Ready" in paper or "production-ready" in paper,
        },
        "source_characteristics": {
            "success_literal_true_occurrences": source.count('"success": True'),
            "hard_coded_hypothesis_quality_0_85": '"hypothesis_quality": 0.85' in source,
            "default_regulatory_score_0_85": "get('regulatory_score', 0.85)" in source,
            "throughput_is_elapsed_time_derived": (
                "len(self.research_outputs) / (total_duration / 60)" in source
            ),
            "source_writes_machine_readable_result": bool(
                re.search(r"write_text|json\.dump|open\([^\n]+['\"]w", source)
            ),
        },
        "preserved_candidate_result_artifacts": sorted(preserved),
        "reference_section_is_placeholder": (
            "[In a real publication, this would include comprehensive references" in paper
        ),
        "digest_or_signature_present_in_paper": bool(
            re.search(r"SHA-256|signature|attestation|Sigstore", paper, re.IGNORECASE)
        ),
        "assessment": "not_usable_as_positive_system_validation_evidence",
    }


def audit_axiom_paper(root: Path) -> dict[str, Any]:
    papers = [file_record(root / path, root) for path in AXIOM_PAPERS]
    texts = [read_text(root / path) for path in AXIOM_PAPERS]
    latest = texts[0]
    result_path = root / AXIOM_RESULT
    result = json.loads(read_text(result_path))
    statuses = []
    for section in (result.get("meta_4_validation") or {}).values():
        if isinstance(section, dict):
            statuses.extend(section.values())
    scores = ["0.581", "0.578", "0.559", "0.111", "0.933", "0.944", "0.878"]
    return {
        "manuscripts": papers,
        "all_three_are_byte_identical": len({item["sha256"] for item in papers}) == 1,
        "supporting_json": file_record(result_path, root),
        "supporting_json_status_strings": len(statuses),
        "supporting_json_status_value_counts": dict(sorted(Counter(statuses).items())),
        "supporting_json_contains_claimed_scores": {
            score: score in read_text(result_path) for score in scores
        },
        "appendix_placeholder_lines": [
            line for line in latest.splitlines() if line.startswith("[") and line.endswith("]")
        ],
        "appendix_placeholder_count": sum(
            line.startswith("[") and line.endswith("]") for line in latest.splitlines()
        ),
        "claimed_repository_url": "https://github.com/axiom-research/meta4-evaluation",
        "local_path_for_claimed_repository_exists": (
            root / "atlas/meta4-evaluation"
        ).exists(),
        "paper_contains_content_digest": "SHA-256" in latest or "sha256" in latest.lower(),
        "paper_contains_signature_or_attestation": bool(
            re.search(r"signature|attestation|sigstore", latest, re.IGNORECASE)
        ),
        "paper_contains_seed": bool(re.search(r"\bseed\b", latest, re.IGNORECASE)),
        "paper_contains_statistical_test_values": bool(
            re.search(r"\bp\s*[=<]|confidence interval|effect size", latest, re.IGNORECASE)
        ),
        "assessment": "incomplete_template_not_usable_as_scientific_result",
    }


def audit_dna_paper(root: Path) -> dict[str, Any]:
    md_path = root / AMY_DNA_STEM.with_suffix(".md")
    pdf_path = root / AMY_DNA_STEM.with_suffix(".pdf")
    text = read_text(md_path)
    cited_records = extract_backtick_paths(text, "data/experiments/biology_")
    records = [provenance_record(root / path, root) for path in cited_records]
    artifact_paths = extract_backtick_paths(
        text,
        "artifacts/Computational_Analysis_of_DNA_Sequence_and_Protein_Analysis/",
    )
    e2 = next((item for item in records if item.get("tool_name") == "numpy_statistics"), {})
    e3 = next((item for item in records if item.get("tool_name") == "dna_analyzer"), {})
    pdf_digest = sha256(pdf_path)
    return {
        "manuscript_files": {
            suffix: file_record(root / AMY_DNA_STEM.with_suffix(suffix), root)
            for suffix in (".md", ".tex", ".pdf")
        },
        "cited_provenance_paths": cited_records,
        "provenance_summary": summarize_provenance(records),
        "records": records,
        "declared_artifact_paths": artifact_paths,
        "declared_artifact_existence": {
            path: (root / path).is_file() for path in artifact_paths
        },
        "declared_artifact_count": len(artifact_paths),
        "missing_declared_artifact_count": sum(
            not (root / path).is_file() for path in artifact_paths
        ),
        "literal_reasoning_tag_leaks": text.count("</think>"),
        "duplicated_discussion_anchor_count": text.count(
            "The computational evidence presented here is modest in scope"
        ),
        "e2_input": e2.get("tool_input"),
        "e3_input": e3.get("tool_input"),
        "e2_and_e3_are_measurements_of_same_sequence": False,
        "paper_claims_e2_e3_gc_agreement": "agreement between E2 and E3 regarding GC content" in text,
        "closest_literature_audit": {
            "official_primary_source_urls": DNA_CLOSEST_LITERATURE_SOURCES,
            "all_three_named_works_resolve_to_real_publisher_records": True,
            "declared_novelty_audit_artifact_present": (
                root
                / "artifacts/Computational_Analysis_of_DNA_Sequence_and_Protein_Analysis/"
                "literature_novelty_audit.json"
            ).is_file(),
            "query_corpus_ranking_and_title_overlap_replayable": False,
            "interpretation": (
                "Existence of the three named works does not validate the manuscript's "
                "unretained search, title-overlap method, ranking, or novelty boundary."
            ),
        },
        "pdf_visual_review": {
            "review_type": "manual_page_render_plus_pdfinfo_and_pdftotext",
            "reviewed_pdf_sha256": DNA_PDF_VISUALLY_REVIEWED_SHA256,
            "review_applies_to_current_pdf_bytes": (
                pdf_digest == DNA_PDF_VISUALLY_REVIEWED_SHA256
            ),
            "page_count": 6,
            "a4_pages": True,
            "anonymous_title_metadata": True,
            "tagged_pdf": False,
            "fonts_embedded": False,
            "visible_reasoning_tag": True,
            "literal_markdown_heading_visible": "## Testable Predictions",
            "markdown_sections_absent_from_pdf": [
                "Acknowledgments",
                "Data Availability",
                "Provenance Watermark",
            ],
            "long_artifact_paths_break_across_lines": True,
            "machine_epsilon_symbol_has_missing_glyphs": True,
            "content_equivalent_to_markdown": False,
            "publication_ready": False,
        },
        "unsupported_or_overbroad_phrases": {
            "replication_on_independent_hardware": "allowing replication on independent hardware" in text,
            "machine_epsilon_verified": "Numerical precision was verified to machine epsilon" in text,
            "methodologically_distinct_frameworks": "methodologically distinct frameworks" in text,
            "mps_acceleration": "MPS acceleration" in text,
        },
        "assessment": "not_usable_as_a_scientific_manuscript_without_reconstruction",
    }


def audit_bond_paper(root: Path) -> dict[str, Any]:
    path = root / BOND_PAPER
    copy_path = root / BOND_PAPER_COPY
    text = read_text(path)
    cited = extract_backtick_paths(text, "data/experiments/chemistry_bond_energy_analyzer_")
    records = [provenance_record(root / item, root) for item in cited]
    tool_source = read_text(root / ATLAS_TOOL_SOURCE)
    hunt_source = read_text(root / BOND_HUNT_SOURCE)
    return {
        "manuscript": file_record(path, root),
        "duplicate_manuscript": file_record(copy_path, root),
        "duplicate_is_byte_identical": path.read_bytes() == copy_path.read_bytes(),
        "cited_provenance_paths": cited,
        "provenance_summary": summarize_provenance(records),
        "records": records,
        "producer_source": file_record(root / BOND_HUNT_SOURCE, root),
        "tool_source": file_record(root / ATLAS_TOOL_SOURCE, root),
        "source_characteristics": {
            "experiment_ids_use_md5_truncation": "hashlib.md5(inp.encode()).hexdigest()[:6]" in hunt_source,
            "output_digest_uses_sha256": "hashlib.sha256(out.encode()).hexdigest()" in hunt_source,
            "producer_writes_output_txt": '(d / "output.txt").write_text(out)' in hunt_source,
            "tool_is_a_literal_lookup_table": (
                "def _bond_energy_analyzer" in tool_source and "bond_energies = {" in tool_source
            ),
        },
        "internal_contradictions_or_irrelevancies": {
            "introduction_says_eight_methods": "we employ 8 computational methods" in text,
            "methods_says_single_tool": "We employed a single computational tool" in text,
            "discussion_mentions_unmeasured_homo_lumo": "HOMO-LUMO gap scaling" in text,
            "paper_claims_environment_but_records_lack_it": (
                "execution environment" in text
                and summarize_provenance(records)["environment_present"] == 0
            ),
            "paper_claims_machine_epsilon": "Numerical precision was verified to machine epsilon" in text,
            "paper_claims_mps": "MPS acceleration" in text,
        },
        "assessment": "hard_coded_table_lookup_not_an_empirical_chemistry_validation",
    }


def bib_block(text: str, key: str) -> str:
    marker = "{" + key + ","
    start = text.index(marker)
    end = text.find("\n@", start)
    if end < 0:
        end = len(text)
    return text[start:end]


def audit_formal_references(paper_worktree: Path) -> dict[str, Any]:
    md_path = paper_worktree / FORMAL_MD
    bib_path = paper_worktree / FORMAL_BIB
    md = read_text(md_path)
    bib = read_text(bib_path)
    bib_keys = sorted(re.findall(r"^@[A-Za-z]+\{([^,]+),", bib, re.MULTILINE))
    citation_keys = sorted(set(re.findall(r"\[@([A-Za-z0-9_:.-]+)\]", md)))
    wang = bib_block(bib, "wang2026provenance")
    local_wang_authors = [
        "Yiqi Wang",
        "Jiaqi Zhang",
        "Taotao Cai",
        "Zirui Liu",
        "Qingqiang Sun",
        "Zequn Sun",
        "Zhangkai Wu",
        "Manqing Dong",
        "Mingkai Zheng",
        "Xuefei Yin",
        "Yanming Zhu",
    ]
    return {
        "paper": file_record(md_path, paper_worktree),
        "bibliography": file_record(bib_path, paper_worktree),
        "bibliography_keys": bib_keys,
        "citation_keys": citation_keys,
        "bibliography_entry_count": len(bib_keys),
        "unique_citation_key_count": len(citation_keys),
        "undefined_citations": sorted(set(citation_keys) - set(bib_keys)),
        "uncited_bibliography_entries": sorted(set(bib_keys) - set(citation_keys)),
        "official_primary_source_urls": OFFICIAL_REFERENCE_SOURCES,
        "metadata_discrepancies": [
            {
                "key": "wang2026provenance",
                "official_source": OFFICIAL_REFERENCE_SOURCES["wang2026provenance"],
                "local_title": (
                    "From Agent Traces to Trust: A Survey of Evidence Tracing and "
                    "Execution Provenance in LLM Agents"
                ),
                "current_official_title": WANG_CURRENT_TITLE,
                "local_authors": local_wang_authors,
                "current_official_authors": WANG_CURRENT_AUTHORS,
                "title_matches": "A Survey of Evidence Tracing" not in wang,
                "authors_match": local_wang_authors == WANG_CURRENT_AUTHORS,
            }
        ],
        "arxiv_preprint_entry_count": bib.count("journal = {arXiv preprint"),
        "method_citation_boundary": {
            "mcnemar_supports_correlated_binary_pair_method_in_general": True,
            "efron_supports_bootstrap_method_in_general": True,
            "holm_supports_multiple_test_adjustment_in_general": True,
            "those_citations_establish_case_seed_independence_for_this_design": False,
        },
    }


def build_audit(repository_root: Path, paper_worktree: Path) -> dict[str, Any]:
    missing_inputs: list[str] = []

    def capture(
        audit_name: str,
        operation: Any,
    ) -> dict[str, Any]:
        try:
            return operation()
        except FileNotFoundError as exc:
            missing = Path(str(exc.filename)) if exc.filename else Path("unknown")
            for label, root in (
                ("repository", repository_root),
                ("paper_worktree", paper_worktree),
            ):
                try:
                    locator = f"{label}:{missing.relative_to(root).as_posix()}"
                    break
                except ValueError:
                    continue
            else:
                locator = f"unresolved:{missing.name}"
            missing_inputs.append(locator)
            return {
                "audit_available": False,
                "audit_name": audit_name,
                "missing_required_input": locator,
                "scientific_claims_authorized": False,
            }

    amy_revised = capture(
        "amy_revised_benchmark",
        lambda: audit_amy_revised(repository_root),
    )
    atlas_paper = capture(
        "atlas_system_paper",
        lambda: audit_atlas_paper(repository_root),
    )
    axiom_paper = capture(
        "axiom_meta4_paper",
        lambda: audit_axiom_paper(repository_root),
    )
    dna_paper = capture(
        "amy_latest_dna_paper",
        lambda: audit_dna_paper(repository_root),
    )
    bond_paper = capture(
        "atlas_bond_energy_paper",
        lambda: audit_bond_paper(repository_root),
    )
    references = capture(
        "formal_system_paper_references",
        lambda: audit_formal_references(paper_worktree),
    )

    findings = [
        {
            "id": "LM01",
            "severity": "blocking",
            "fact": "The revised A.M.Y benchmark names only eight representative records while the prefix it says enumerates 24 currently selects 96; the source manuscript is required to identify the intended 24.",
        },
        {
            "id": "LM02",
            "severity": "blocking",
            "fact": "The 24 intended A.M.Y outputs match their stored SHA-256, but none carries authentication, source revision, dependency identity, or a seed field.",
        },
        {
            "id": "LM03",
            "severity": "blocking",
            "fact": "The ATLAS system paper preserves no machine-readable result for its 3/3, 23.17-second, or 7.77-workflows/minute claims and has a placeholder reference section.",
        },
        {
            "id": "LM04",
            "severity": "blocking",
            "fact": "The AXIOM paper is three byte-identical template copies with eleven explicit appendix placeholders; its retained META4 JSON contains status strings rather than the manuscript's model scores.",
        },
        {
            "id": "LM05",
            "severity": "blocking",
            "fact": "The newest DNA manuscript declares four publication artifacts that are absent, leaks a reasoning tag, duplicates its discussion, and treats unrelated inputs as corroborating GC measurements.",
        },
        {
            "id": "LM06",
            "severity": "blocking",
            "fact": "The bond-energy paper is an eight-query readout of a literal lookup table, not an empirical chemistry validation; its records contain no environment despite the paper claiming one.",
        },
        {
            "id": "LM07",
            "severity": "major",
            "fact": "All 14 formal-paper bibliography entries are cited, but arXiv:2606.04990 has stale/incorrect local title and author metadata relative to the current official record.",
        },
        {
            "id": "LM08",
            "severity": "major",
            "fact": "General McNemar, bootstrap, and Holm references do not establish independence of repeated case-seed observations in the formal benchmark.",
        },
        {
            "id": "LM09",
            "severity": "major",
            "fact": "The revised A.M.Y benchmark cites Stodden et al. as 2014 while the official Science record is 2016 (354(6317):1240-1241, doi:10.1126/science.aah6168).",
        },
        {
            "id": "LM10",
            "severity": "blocking",
            "fact": "The visually reviewed DNA PDF is not content-equivalent to its Markdown: it omits acknowledgments, data availability, and the provenance watermark while visibly retaining a reasoning tag and literal Markdown syntax.",
        },
        {
            "id": "LM11",
            "severity": "blocking",
            "fact": "The DNA paper's three closest-literature titles resolve to publisher records, but the declared novelty-audit artifact is absent, so its search corpus, query, title-overlap calculation, and ranking cannot be replayed.",
        },
    ]
    if missing_inputs:
        findings = []
    return {
        "schema_version": "amy.latest-manuscripts-audit.v2",
        "scope": {
            "repository_root": str(repository_root),
            "paper_worktree": str(paper_worktree),
            "audit_date": "2026-07-13",
            "current_bytes_only": True,
        },
        "safety": {
            "project_code_imported": False,
            "scientific_tools_executed": False,
            "model_or_provider_contacted": False,
            "private_key_bytes_read": False,
            "audited_files_modified": False,
        },
        "amy_revised_benchmark": amy_revised,
        "atlas_system_paper": atlas_paper,
        "axiom_meta4_paper": axiom_paper,
        "amy_latest_dna_paper": dna_paper,
        "atlas_bond_energy_paper": bond_paper,
        "formal_system_paper_references": references,
        "findings": findings,
        "replay_status": {
            "complete": not missing_inputs,
            "missing_required_inputs": sorted(set(missing_inputs)),
            "absence_treated_as_success": False,
            "scientific_claims_authorized": False,
        },
        "overall_assessment": {
            "legacy_manuscripts_fit_as_positive_scientific_evidence": False,
            "legacy_manuscripts_may_be_cited_as_audited_project_history": True,
            "formal_bibliography_ready_without_correction": False,
            "confirmatory_claim_permitted": False,
            "recommended_disposition": (
                "Do not repair these manuscripts in place. Preserve them as historical artifacts, "
                "cite only bounded audited observations, and build the new paper from a frozen, "
                "authenticated, preregistered evidence package."
            ),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-root", type=Path, default=DEFAULT_REPOSITORY_ROOT)
    parser.add_argument("--paper-worktree", type=Path, default=DEFAULT_PAPER_WORKTREE)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--compact", action="store_true")
    args = parser.parse_args()
    result = build_audit(args.repository_root.resolve(), args.paper_worktree.resolve())
    rendered = json.dumps(
        result,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":") if args.compact else None,
        indent=None if args.compact else 2,
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
