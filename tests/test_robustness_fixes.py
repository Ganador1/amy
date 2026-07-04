#!/usr/bin/env python3
"""Hermetic tests for the robustness-tail fixes from the 2026-06-27 audit.

Covers: JSON last-resort parsing is O(n) (not O(n^2) event-loop freeze),
deterministic_evolve no longer IndexErrors, _escape_latex escapes the full
special set, world_model logs the true prior, and SemanticMemory.add_fact
tolerates facts without a 'sources' list.
"""
import time

import pytest

from cognition.reasoning import _parse_json_robust, _first_balanced_object
from cognition.evolution_agent import deterministic_evolve
from communication.paper_generator import PaperGenerator
from core.world_model import WorldModel
from memory.semantic import SemanticMemory


# ── JSON last-resort parsing: linear + still correct ─────────────────────────

def test_first_balanced_object_extracts_first_object():
    assert _first_balanced_object('noise {"a": 1} trailing') == '{"a": 1}'


def test_first_balanced_object_honors_braces_in_strings():
    assert _first_balanced_object('{"k": "a } b"}') == '{"k": "a } b"}'


def test_parse_json_robust_recovers_embedded_object():
    txt = 'here is the answer:\n{"observation": "x", "action_type": "think_more"}\nthanks'
    out = _parse_json_robust(txt)
    assert out["action_type"] == "think_more"


def test_parse_json_robust_is_fast_on_large_malformed_input():
    # A big brace-wrapped-but-unparseable blob used to take seconds (O(n^2));
    # the linear scan must finish well under a second.
    big = "{" + ("x" * 20000)  # opens a brace, never closes, not valid JSON
    t0 = time.monotonic()
    with pytest.raises(Exception):
        _parse_json_robust(big)
    assert time.monotonic() - t0 < 1.0


# ── deterministic_evolve combination never IndexErrors ───────────────────────

@pytest.mark.parametrize("second", [
    {"elo": 1200},                       # no hypothesis key
    {"hypothesis": ""},                  # empty
    {"hypothesis": "   "},               # whitespace
    {"hypothesis": "Testable via: x"},   # only a test clause -> text2==""
])
def test_deterministic_evolve_combination_handles_empty_second(second):
    parent = {"hypothesis": "Prime gaps grow like log(n). Testable via: measure."}
    out = deterministic_evolve(parent, "combination", second_parent=second)
    assert isinstance(out, dict)
    assert out.get("hypothesis")  # produced something, did not raise


def test_deterministic_evolve_combination_normal_case():
    parent = {"hypothesis": "A holds"}
    second = {"hypothesis": "B also holds"}
    out = deterministic_evolve(parent, "combination", second_parent=second)
    assert "moreover" in out["hypothesis"]


def test_deterministic_evolve_keeps_ssh_tests_deterministic():
    parent = {
        "hypothesis": (
            "The SSH edge-state interpretation is directly testable by "
            "eigenvector localization: for delta=0.025000, "
            "localization_onset_n=16, max_pair_edge_weight=0.271313, "
            "max_pair_ipr=0.094124, and min_participation_sites=10.624256 "
            "should co-occur with the small topological frontier gap."
        ),
        "method": (
            "Rerun ssh_edge_localization_map with denser chain lengths and "
            "require the edge weight/IPR signal to remain localized."
        ),
        "novelty_status": "candidate_novelty",
        "confidence": 0.66,
    }

    out = deterministic_evolve(parent, "grounding", domain="chemistry")
    combined = out["hypothesis"] + " " + out.get("method", "")

    assert "ssh_edge_localization_map" in combined
    assert "denser chain lengths" in combined
    assert "edge weight/ipr" in combined.lower()
    assert "confidence interval" not in combined.lower()
    assert "standard error" not in combined.lower()
    assert "p-value" not in combined.lower()


# ── _escape_latex escapes the full special set ───────────────────────────────

def test_escape_latex_handles_subscripts_and_specials():
    esc = PaperGenerator._escape_latex("E_n = -13.6/n^2 eV; set {a,b}; 50% ~ $5")
    for raw in ("_", "^", "{", "}", "~", "$"):
        # No BARE special should remain (each appears only inside an escape seq).
        assert f" {raw} " not in f" {esc} " or "\\" in esc
    assert r"\_" in esc
    assert r"\textasciicircum{}" in esc
    assert r"\$" in esc


def test_escape_latex_preserves_markdown_bold():
    esc = PaperGenerator._escape_latex("this is **bold** text")
    assert r"\textbf{bold}" in esc


# ── world_model logs the true prior on contradiction ─────────────────────────

async def test_world_model_contradiction_updates_value_correctly():
    wm = WorldModel.__new__(WorldModel)
    wm.beliefs = {}
    fact = {"subject": "sky", "predicate": "is", "object": "blue"}
    await wm.update_beliefs({"new_facts": [{**fact, "confidence": 0.9}]}, {})
    # A strongly contradicting observation (gap >= 0.2 -> contradiction branch).
    await wm.update_beliefs({"new_facts": [{**fact, "confidence": 0.1}]}, {})
    b = wm.beliefs["sky:is:blue"]
    assert b.times_contradicted == 1
    assert b.confidence == pytest.approx(0.5)  # (0.9 + 0.1)/2 — value correct


# ── semantic add_fact tolerates a fact without 'sources' ─────────────────────

async def test_add_fact_tolerates_missing_sources_list(monkeypatch):
    sm = SemanticMemory.__new__(SemanticMemory)
    sm.facts = {
        "a|b|c": {  # documented singular-'source' schema, no 'sources' list
            "subject": "a", "predicate": "b", "object": "c",
            "confidence": 0.8, "source": "old", "times_seen": 1,
        }
    }
    sm.max_sources_per_fact = 25  # __new__ bypassed __init__
    async def _noop():
        return None
    monkeypatch.setattr(sm, "_maybe_save", _noop)  # avoid disk
    # Must not KeyError on re-observation.
    await sm.add_fact("a", "b", "c", confidence=0.6, source="new")
    assert "new" in sm.facts["a|b|c"]["sources"]
