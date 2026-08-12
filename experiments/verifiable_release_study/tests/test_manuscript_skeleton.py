"""Stage-discipline tests for the manuscript skeleton.

The skeleton may contain Introduction, Background, Threat Model, Profiles,
Study Design, case-study structure, Limitations, and Availability. Abstract,
Results, Discussion, and Conclusion must stay locked to their FORBIDDEN
placeholders until the corresponding lineage gate opens.
"""

import importlib.util
import sys
from pathlib import Path

PAPER_DIR = Path(__file__).resolve().parents[1] / "paper"
SKELETON = PAPER_DIR / "MANUSCRIPT_SKELETON.md"
LINTER = PAPER_DIR / "lint_manuscript.py"


def _load_linter():
    spec = importlib.util.spec_from_file_location("lint_manuscript", LINTER)
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("lint_manuscript", module)
    spec.loader.exec_module(module)
    return module


def test_skeleton_exists_and_passes_lint():
    assert SKELETON.is_file()
    linter = _load_linter()
    violations = linter.lint(SKELETON)
    assert violations == [], "\n".join(violations)


def test_gated_sections_locked():
    text = SKELETON.read_text(encoding="utf-8")
    for placeholder in (
        "[ABSTRACT-FORBIDDEN-UNTIL-R1]",
        "[RESULTS-FORBIDDEN-UNTIL-R1]",
        "[DISCUSSION-FORBIDDEN-UNTIL-R1]",
        "[CONCLUSION-FORBIDDEN-UNTIL-R1-AND-EXTERNAL-REPRODUCTION]",
    ):
        assert placeholder in text, f"missing gate placeholder {placeholder}"


def test_linter_rejects_prose_in_results(tmp_path):
    linter = _load_linter()
    text = SKELETON.read_text(encoding="utf-8")
    poisoned = text.replace(
        "`[RESULTS-FORBIDDEN-UNTIL-R1]`",
        "`[RESULTS-FORBIDDEN-UNTIL-R1]`\n\nP3 rejected 185/185 target-invalid cases.",
    )
    tmp = tmp_path / "poisoned.md"
    tmp.write_text(poisoned, encoding="utf-8")
    violations = linter.lint(tmp)
    rules = {v.split()[1] for v in violations}
    assert "RULE:gated-exact" in rules
    assert "RULE:numeric-outcome" in rules


def test_linter_rejects_forbidden_vocabulary(tmp_path):
    linter = _load_linter()
    text = SKELETON.read_text(encoding="utf-8")
    poisoned = text.replace(
        "## 1. Introduction",
        "## 1. Introduction\n\nOur releases are blockchain-validated and 100% reproducible.",
        1,
    )
    tmp = tmp_path / "vocab.md"
    tmp.write_text(poisoned, encoding="utf-8")
    violations = linter.lint(tmp)
    assert any("RULE:forbidden-phrase" in v for v in violations)


def test_linter_rejects_code_span_and_comment_gate_bypasses(tmp_path):
    linter = _load_linter()
    text = SKELETON.read_text(encoding="utf-8")
    code_poisoned = text.replace(
        "`[RESULTS-FORBIDDEN-UNTIL-R1]`",
        "`[RESULTS-FORBIDDEN-UNTIL-R1]`\n\n`P3 accepted 100%`",
    )
    code_path = tmp_path / "code-poisoned.md"
    code_path.write_text(code_poisoned, encoding="utf-8")
    code_rules = {v.split()[1] for v in linter.lint(code_path)}
    assert "RULE:gated-exact" in code_rules
    assert "RULE:numeric-outcome" in code_rules

    comment_poisoned = text.replace(
        "`[DISCUSSION-FORBIDDEN-UNTIL-R1]`",
        "`[DISCUSSION-FORBIDDEN-UNTIL-R1]`\n\n<!-- P3 rejected 185/185. -->",
    )
    comment_path = tmp_path / "comment-poisoned.md"
    comment_path.write_text(comment_poisoned, encoding="utf-8")
    comment_rules = {v.split()[1] for v in linter.lint(comment_path)}
    assert "RULE:gated-comment" in comment_rules
    assert "RULE:numeric-outcome" in comment_rules


def test_linter_rejects_duplicate_placeholder(tmp_path):
    linter = _load_linter()
    text = SKELETON.read_text(encoding="utf-8")
    poisoned = text.replace(
        "`[ABSTRACT-FORBIDDEN-UNTIL-R1]`",
        "`[ABSTRACT-FORBIDDEN-UNTIL-R1]`\n`[ABSTRACT-FORBIDDEN-UNTIL-R1]`",
    )
    tmp = tmp_path / "duplicate-placeholder.md"
    tmp.write_text(poisoned, encoding="utf-8")
    assert any("RULE:gated-placeholder" in v for v in linter.lint(tmp))


def test_linter_rejects_forbidden_wording_inside_inline_code(tmp_path):
    linter = _load_linter()
    text = SKELETON.read_text(encoding="utf-8")
    poisoned = text.replace(
        "## 1. Introduction",
        "## 1. Introduction\n\n`immutable deposit` [SPECIFIED]",
        1,
    )
    tmp = tmp_path / "inline-code.md"
    tmp.write_text(poisoned, encoding="utf-8")
    assert any("RULE:forbidden-phrase" in v for v in linter.lint(tmp))


def test_external_claims_require_known_source_ids(tmp_path):
    linter = _load_linter()
    text = SKELETON.read_text(encoding="utf-8")
    missing = text.replace(
        "## 1. Introduction",
        "## 1. Introduction\n\nExternal factual claim. [EXTERNAL]",
        1,
    )
    missing_path = tmp_path / "missing-source.md"
    missing_path.write_text(missing, encoding="utf-8")
    assert any("RULE:external-source" in v for v in linter.lint(missing_path))

    unknown = text.replace(
        "## 1. Introduction",
        "## 1. Introduction\n\nExternal factual claim [S999]. [EXTERNAL]",
        1,
    )
    unknown_path = tmp_path / "unknown-source.md"
    unknown_path.write_text(unknown, encoding="utf-8")
    assert any("RULE:unknown-source" in v for v in linter.lint(unknown_path))


def test_related_work_has_no_unresolved_citation_slots():
    text = SKELETON.read_text(encoding="utf-8")
    assert "[CITE:" not in text


def test_manuscript_does_not_claim_registration_has_occurred():
    text = SKELETON.read_text(encoding="utf-8")
    assert "## 5. Study Design (Draft; Not Yet Preregistered)" in text
    assert "## 5. Study Design (Preregistered)" not in text


def test_no_handwritten_result_counts_outside_design_markers():
    """Design-state counts are allowed only where explicitly marked as
    regenerate-from-R0; the skeleton currently defers all counts, so any
    bare 'N/M' fraction anywhere in prose is a defect at this stage."""
    linter = _load_linter()
    text = SKELETON.read_text(encoding="utf-8")
    prose = linter._strip_non_prose(text)
    assert linter.NUMERIC_OUTCOME.search(prose) is None, (
        "skeleton contains a hand-written outcome-style number; "
        "counts must be generated from frozen R0 bytes"
    )
