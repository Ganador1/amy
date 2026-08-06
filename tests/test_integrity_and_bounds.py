#!/usr/bin/env python3
"""Hermetic coverage for integrity + bounded-memory guarantees (2026-06-27 audit gaps).

- ProvenanceManager: output_hash is the exact SHA-256 of the output, and a
  repeated experiment_id never overwrites — it gets a distinct '<id>_2' dir.
- record_safety_event: hashes (not stores) the prompt and chains each line to
  the previous one.
- Heartbeat bounded buffers: the deques evict past their maxlen.
"""
import hashlib
import asyncio
import json
import shutil
import subprocess
from collections import deque
from pathlib import Path

import pytest

import communication.paper_generator as paper_generator
from communication.paper_generator import PaperGenerator
from core.provenance import ProvenanceManager


# ── Provenance integrity ─────────────────────────────────────────────────────

def test_output_hash_is_exact_sha256(tmp_path):
    pm = ProvenanceManager(base_dir=tmp_path)
    output = "Total energy: -1.11675931 Ha\nconverged in 8 cycles"
    rec = pm.record_execution(
        tool_name="pyscf_hf_energy", tool_input="H2", tool_output=output,
        success=True, duration_seconds=0.5, domain="chemistry",
    )
    assert rec["tool"]["output_hash"] == hashlib.sha256(output.encode("utf-8")).hexdigest()
    # And the on-disk output.txt round-trips to the same hash.
    out_file = tmp_path / rec["experiment_id"] / "output.txt"
    assert hashlib.sha256(out_file.read_bytes()).hexdigest() == rec["tool"]["output_hash"]


def test_repeated_experiment_id_does_not_overwrite(tmp_path):
    pm = ProvenanceManager(base_dir=tmp_path)
    r1 = pm.record_execution("t", "in", "out-A", True, 0.1, experiment_id="exp_fixed")
    r2 = pm.record_execution("t", "in", "out-B", True, 0.1, experiment_id="exp_fixed")
    assert r1["experiment_id"] == "exp_fixed"
    assert r2["experiment_id"] == "exp_fixed_2"
    # Both provenance files survive with their own outputs.
    assert (tmp_path / "exp_fixed" / "output.txt").read_text() == "out-A"
    assert (tmp_path / "exp_fixed_2" / "output.txt").read_text() == "out-B"


def test_unsafe_experiment_id_is_rejected_before_filesystem_lookup(tmp_path):
    pm = ProvenanceManager(base_dir=tmp_path / "provenance")
    with pytest.raises(ValueError, match="invalid experiment_id"):
        pm.record_execution(
            "t",
            "in",
            "out",
            True,
            0.1,
            experiment_id="../../outside",
        )
    assert not (tmp_path / "outside").exists()


def test_provenance_verification_rehashes_retained_output(tmp_path):
    pm = ProvenanceManager(base_dir=tmp_path)
    record = pm.record_execution("t", "in", "original", True, 0.1, experiment_id="exp_fixed")
    verified = pm.verify_experiment_id(record["experiment_id"])
    assert verified["integrity_verified"] is True
    assert verified["authenticated"] is False
    assert verified["rollback_protected"] is False

    (tmp_path / "exp_fixed" / "output.txt").write_text("tampered", encoding="utf-8")
    tampered = pm.verify_experiment_id(record["experiment_id"])
    assert tampered["exists"] is True
    assert tampered["integrity_verified"] is False


# ── Publication evidence binding and fail-closed gates ──────────────────────

def _record_paper_evidence(monkeypatch, tmp_path, output: str = "2 + 2 = 4") -> dict:
    experiments_dir = tmp_path / "experiments"
    record = ProvenanceManager(base_dir=experiments_dir).record_execution(
        "deterministic_calculator",
        "2 + 2",
        output,
        True,
        0.01,
        experiment_id="exp_paper_evidence",
    )
    monkeypatch.setattr(paper_generator, "EXPERIMENTS_DIR", experiments_dir)
    return record


def _passing_reflection(md_content: str) -> dict:
    return {
        "annotated_md": (
            md_content
            + "\n\n## Self-Review (Reflection Agent)\n\n"
            "Internal self-review passed for artifact-equivalence testing.\n"
        ),
        "score": 100.0,
        "pass_overall": True,
        "n_high": 0,
        "n_medium": 0,
        "n_low": 0,
        "issues": [],
    }


def _minimal_sections(extra_result_text: str = "") -> list[dict]:
    return [
        {"heading": "Methods", "content": "A deterministic retained output was inspected."},
        {
            "heading": "Results",
            "content": f"The retained output contains an exact arithmetic statement. {extra_result_text}".strip(),
        },
        {"heading": "Discussion", "content": "No claim beyond the retained bytes is made."},
        {"heading": "Conclusion", "content": "This is a pipeline regression artifact."},
    ]


def test_fact_cannot_borrow_unrelated_output_hash(monkeypatch, tmp_path):
    record = _record_paper_evidence(monkeypatch, tmp_path, output="2 + 2 = 4")
    output_hash = record["tool"]["output_hash"]
    experiment_id = record["experiment_id"]

    borrowed_hash_fact = {
        "claim": "The Moon is made of cheese",
        "experiment_id": experiment_id,
        "output_sha256": output_hash,
        "evidence_binding": {
            "type": "exact_fragment_v1",
            "claim": "The Moon is made of cheese",
            "fragment": "2 + 2 = 4",
            "experiment_id": experiment_id,
            "output_sha256": output_hash,
        },
    }
    exact_fact = {
        "claim": "2 + 2 = 4",
        "experiment_id": experiment_id,
        "output_sha256": output_hash,
        "evidence_binding": {
            "type": "exact_fragment_v1",
            "claim": "2 + 2 = 4",
            "fragment": "2 + 2 = 4",
            "experiment_id": experiment_id,
            "output_sha256": output_hash,
        },
    }

    assert paper_generator._evidence_bound_facts(
        [borrowed_hash_fact],
        [experiment_id],
    ) == []
    assert paper_generator._evidence_bound_facts(
        [exact_fact],
        [experiment_id],
    ) == [exact_fact]


def test_paper_without_experiment_evidence_is_rejected(monkeypatch, tmp_path):
    monkeypatch.setattr(
        PaperGenerator,
        "_run_reflection_gate",
        staticmethod(_passing_reflection),
    )
    result = asyncio.run(
        PaperGenerator(enhance=False, output_dir=tmp_path).generate_paper(
            title="No Evidence Must Not Publish",
            abstract="This draft intentionally supplies no experiment evidence.",
            sections=_minimal_sections(),
            experiment_ids=[],
        )
    )

    assert result["publication_status"] == "rejected"
    assert "no experiment evidence supplied" in result["rejection_reasons"]
    assert result["pdf_path"] is None


def test_identical_rejected_drafts_reuse_the_first_artifact(tmp_path):
    generator = PaperGenerator(enhance=False, output_dir=tmp_path)
    kwargs = {
        "title": "Repeated deterministic fixture",
        "md_content": "# Repeated deterministic fixture\n\nSame bytes.\n",
        "section_count": 1,
        "reasons": ["fixture rejection"],
        "grounding_repair": {"repairs": 0, "items": []},
        "publication_artifacts": {"tables": [], "figures": []},
    }

    first = generator._reject_draft(md_path=tmp_path / "first.md", **kwargs)
    second = generator._reject_draft(md_path=tmp_path / "second.md", **kwargs)

    assert first["duplicate_draft"] is False
    assert second["duplicate_draft"] is True
    assert second["markdown_path"] == first["markdown_path"]
    assert second["content_sha256"] == first["content_sha256"]
    assert len(list((tmp_path / "rejected").glob("*.md"))) == 1


def test_reflection_exception_rejects_instead_of_publishing(monkeypatch, tmp_path):
    record = _record_paper_evidence(monkeypatch, tmp_path)

    def broken_reflection(_md_content):
        raise RuntimeError("reflection backend unavailable")

    monkeypatch.setattr(
        PaperGenerator,
        "_run_reflection_gate",
        staticmethod(broken_reflection),
    )
    result = asyncio.run(
        PaperGenerator(enhance=False, output_dir=tmp_path).generate_paper(
            title="Review Failure Must Not Publish",
            abstract="A valid evidence record is not sufficient without review.",
            sections=_minimal_sections(),
            experiment_ids=[record["experiment_id"]],
        )
    )

    assert result["publication_status"] == "rejected"
    assert result["rejection_reasons"] == ["reflection review unavailable or invalid"]
    assert result["pdf_path"] is None


def test_pdf_and_latex_preserve_final_markdown_safety_content(monkeypatch, tmp_path):
    record = _record_paper_evidence(monkeypatch, tmp_path)
    monkeypatch.setattr(
        PaperGenerator,
        "_run_reflection_gate",
        staticmethod(_passing_reflection),
    )
    result = asyncio.run(
        PaperGenerator(
            enhance=False,
            include_internal_review=True,
            output_dir=tmp_path,
        ).generate_paper(
            title="Canonical Publication Artifact",
            abstract="All publication formats must preserve the final safety annotations.",
            sections=_minimal_sections(
                "[UNVERIFIED] [SIMULATED — REQUIRES VALIDATION]"
            ),
            experiment_ids=[record["experiment_id"]],
        )
    )

    assert result["publication_status"] == "published", result
    markdown = Path(result["markdown_path"]).read_text(encoding="utf-8")
    latex = Path(result["latex_path"]).read_text(encoding="utf-8")
    pdf_path = Path(result["pdf_path"])
    pdf_bytes = pdf_path.read_bytes()
    pdf_text = None
    if shutil.which("pdftotext"):
        pdf_text = subprocess.run(
            ["pdftotext", str(pdf_path), "-"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout

    required_ascii_markers = (
        "UNVERIFIED",
        "SIMULATED",
        "REQUIRES VALIDATION",
        "Data Availability",
        "Provenance Watermark",
        "Self-Review",
        "AMY-WATERMARK",
    )
    for marker in required_ascii_markers:
        assert marker in markdown
        assert marker in latex
        assert marker.encode("ascii") in pdf_bytes
        if pdf_text is not None:
            assert marker in pdf_text


# ── Safety-event audit log: hash-chained, no plaintext ───────────────────────

def test_real_record_safety_event_hashes_chains_and_hides_plaintext(monkeypatch, tmp_path):
    """Drive the REAL record_safety_event, rerouting its hardcoded log into tmp.

    The function builds the path as
        Path(__file__).resolve().parent.parent / "logs" / "safety_events.jsonl"
    so we monkeypatch the module's Path to a stub whose
    .resolve().parent.parent is tmp_path; the `/ "logs" / ...` then lands in tmp.
    """
    import core.safety_kernel as sk
    from core.safety_kernel import SafetyDecision

    class _StubPath:
        def __init__(self, *_a, **_k):
            pass

        def resolve(self):
            class _R:
                @property
                def parent(self):
                    class _P:
                        @property
                        def parent(self_inner):
                            return tmp_path
                    return _P()
            return _R()

    monkeypatch.setattr(sk, "Path", _StubPath)

    sentinel = "SYNTHESIZE_SARIN_UNIQUE_SENTINEL_12345"
    dec = SafetyDecision(allowed=False, action="block", risk_level="critical",
                         reasons=["x"], matched_rules=["CHEMICAL_WEAPONIZATION"])
    sk.record_safety_event(dec, operation="op1", domain="chemistry", tool_name="t", content=sentinel)
    sk.record_safety_event(dec, operation="op2", domain="chemistry", tool_name="t", content="second")

    log_path = tmp_path / "logs" / "safety_events.jsonl"
    raw = log_path.read_text()
    # 1. The dangerous prompt text is hashed, never stored verbatim.
    assert sentinel not in raw
    lines = log_path.read_bytes().splitlines()
    e1, e2 = json.loads(lines[0]), json.loads(lines[1])
    # 2. content_sha256 matches the sentinel's hash.
    assert e1["content_sha256"] == hashlib.sha256(sentinel.encode()).hexdigest()
    # 3. The chain links: event2.previous_event_hash == sha256(raw line1 incl. newline).
    assert e2["previous_event_hash"] == hashlib.sha256(lines[0] + b"\n").hexdigest()
    # 4. Each event carries its own event_hash.
    assert e1.get("event_hash") and e2.get("event_hash")


# ── Heartbeat bounded buffers ────────────────────────────────────────────────

def test_recent_hypotheses_deque_is_bounded():
    d: deque[str] = deque(maxlen=50)
    for i in range(60):
        d.append(f"h{i}")
    assert len(d) == 50
    assert "h0" not in d and "h9" not in d  # oldest evicted
    assert "h59" in d


def test_tool_results_history_deque_is_bounded():
    d: deque[dict] = deque(maxlen=20)
    for i in range(30):
        d.append({"i": i})
    assert len(d) == 20
    assert d[0]["i"] == 10  # first 10 evicted
    assert d[-1]["i"] == 29
