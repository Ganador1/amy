#!/usr/bin/env python3
"""Manuscript stage linter for the verifiable-release-study paper.

Enforces, mechanically, the skeleton-stage rules declared in
MANUSCRIPT_SKELETON.md and protocol/CLAIM_BOUNDARIES.md:

1. Gated sections (Abstract, Results, Discussion, Conclusion) must contain
   exactly one prescribed FORBIDDEN placeholder and, optionally, a
   FORBIDDEN-UNTIL instruction comment until their gate opens.
2. Forbidden claim vocabulary (CLAIM_BOUNDARIES.md) may not appear in prose.
   Inline-code formatting is not an escape hatch.
3. No numeric outcome statements may appear inside Results/Discussion/
   Conclusion at skeleton stage, including inside comments or code spans.
4. Every EXTERNAL paragraph must cite a source-ledger ID, and every cited
   source-ledger ID must exist.

Exit code 0 = clean; 1 = violations found. Violations print one line each:
    LINE:<n> RULE:<id> <message>

This linter checks stage discipline only. It does not verify evidence labels
against the claim ledger; that belongs to the final-audit tooling.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

GATED_SECTIONS = {
    "## Abstract": "[ABSTRACT-FORBIDDEN-UNTIL-R1]",
    "## 7. Results": "[RESULTS-FORBIDDEN-UNTIL-R1]",
    "## 8. Discussion": "[DISCUSSION-FORBIDDEN-UNTIL-R1]",
    "## 11. Conclusion": "[CONCLUSION-FORBIDDEN-UNTIL-R1-AND-EXTERNAL-REPRODUCTION]",
}

# From protocol/CLAIM_BOUNDARIES.md "Forbidden shortcuts". Matched
# case-insensitively as whole phrases in prose.
FORBIDDEN_PHRASES = [
    r"blockchain[- ]validated",
    r"100%\s+reproducible",
    r"no\s+hallucinations",
    r"all\s+attacks(?!\s+in\s+the\s+frozen)",  # "all attacks in the frozen catalog" is allowed
    r"\bimmutable\b",
    r"independently\s+validated",
    r"signature\s+proves",
    r"validator\s+signatures",
]

NUMERIC_OUTCOME = re.compile(r"\b\d+\s*/\s*\d+\b|\b\d+(?:\.\d+)?\s*%")

COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
CODE_SPAN_RE = re.compile(r"`[^`]*`")
SOURCE_REF_RE = re.compile(r"\[(S\d{2,3})\]")
STUDY_ROOT = Path(__file__).resolve().parents[1]


def _strip_non_prose(text: str) -> str:
    """Blank out HTML comments and inline code spans, preserving line count."""

    def blank(match: re.Match[str]) -> str:
        return re.sub(r"[^\n]", " ", match.group(0))

    text = COMMENT_RE.sub(blank, text)
    return CODE_SPAN_RE.sub(blank, text)


def _strip_comments(text: str) -> str:
    """Blank HTML comments while preserving line count; retain inline code."""

    def blank(match: re.Match[str]) -> str:
        return re.sub(r"[^\n]", " ", match.group(0))

    return COMMENT_RE.sub(blank, text)


def _source_ledger_ids() -> set[str]:
    ledger = STUDY_ROOT / "evidence" / "SOURCE_LEDGER.md"
    if not ledger.is_file():
        return set()
    return set(re.findall(r"^\|\s*(S\d{2,3})\s*\|", ledger.read_text(encoding="utf-8"), re.MULTILINE))


def _section_spans(lines: list[str]) -> dict[str, tuple[int, int]]:
    """Map each '## ' heading to its (start, end) line index range."""
    heads = [(i, ln.strip()) for i, ln in enumerate(lines) if ln.startswith("## ")]
    spans: dict[str, tuple[int, int]] = {}
    for idx, (start, title) in enumerate(heads):
        end = heads[idx + 1][0] if idx + 1 < len(heads) else len(lines)
        spans[title] = (start, end)
    return spans


def lint(path: Path) -> list[str]:
    raw = path.read_text(encoding="utf-8")
    claim_surface = _strip_comments(raw)
    raw_lines = raw.splitlines()
    violations: list[str] = []

    spans = _section_spans(raw_lines)

    # Rule 1: gated sections contain only their placeholder.
    for heading, placeholder in GATED_SECTIONS.items():
        if heading not in spans:
            violations.append(f"LINE:0 RULE:gated-missing section '{heading}' not found")
            continue
        start, end = spans[heading]
        section_raw = "\n".join(raw_lines[start + 1 : end])
        expected = f"`{placeholder}`"
        if section_raw.count(placeholder) != 1:
            violations.append(
                f"LINE:{start + 1} RULE:gated-placeholder '{heading}' must contain exactly one {placeholder}"
            )
        comments = COMMENT_RE.findall(section_raw)
        if any(not comment.removeprefix("<!--").removesuffix("-->").strip().startswith("FORBIDDEN-UNTIL-") for comment in comments):
            violations.append(
                f"LINE:{start + 1} RULE:gated-comment '{heading}' contains a non-gate comment"
            )
        section_without_comments = COMMENT_RE.sub("", section_raw).strip()
        if section_without_comments != expected:
            violations.append(
                f"LINE:{start + 1} RULE:gated-exact '{heading}' must contain only {expected} outside its gate comment"
            )
        if NUMERIC_OUTCOME.search(section_raw):
            violations.append(
                f"LINE:{start + 1} RULE:numeric-outcome numeric result in gated section '{heading}'"
            )

    # Rule 2: forbidden vocabulary in prose.
    for pattern in FORBIDDEN_PHRASES:
        for match in re.finditer(pattern, claim_surface, re.IGNORECASE):
            lineno = claim_surface.count("\n", 0, match.start()) + 1
            violations.append(
                f"LINE:{lineno} RULE:forbidden-phrase {match.group(0)!r}"
            )

    # Rule 4: EXTERNAL paragraphs need a real source-ledger reference, and no
    # source reference may name an unknown ledger ID.
    known_sources = _source_ledger_ids()
    for match in SOURCE_REF_RE.finditer(claim_surface):
        if match.group(1) not in known_sources:
            lineno = claim_surface.count("\n", 0, match.start()) + 1
            violations.append(
                f"LINE:{lineno} RULE:unknown-source [{match.group(1)}] is absent from evidence/SOURCE_LEDGER.md"
            )

    offset = 0
    for paragraph in re.split(r"\n\s*\n", claim_surface):
        start = claim_surface.find(paragraph, offset)
        offset = start + len(paragraph)
        if "[EXTERNAL]" in paragraph and SOURCE_REF_RE.search(paragraph) is None:
            lineno = claim_surface.count("\n", 0, start) + 1
            violations.append(
                f"LINE:{lineno} RULE:external-source EXTERNAL paragraph lacks a source-ledger ID"
            )

    if "[CITE:" in claim_surface:
        for line_no, line in enumerate(claim_surface.splitlines(), start=1):
            if "[CITE:" in line:
                violations.append(
                    f"LINE:{line_no} RULE:unresolved-citation unresolved citation slot"
                )

    return violations


def main(argv: list[str]) -> int:
    target = Path(argv[1]) if len(argv) > 1 else Path(__file__).with_name(
        "MANUSCRIPT_SKELETON.md"
    )
    violations = lint(target)
    for v in violations:
        print(v)
    if violations:
        print(f"FAIL: {len(violations)} violation(s) in {target.name}")
        return 1
    print(f"OK: {target.name} passes skeleton-stage lint")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
