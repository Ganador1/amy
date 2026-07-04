"""
Evolution Agent — iterative refinement of top-ranked hypotheses.

This is the missing piece of A.M.Y's Co-Scientist implementation. The paper
(arXiv:2502.18864, §3.3.5) is explicit that "the co-scientist's **iterative
improvement capability relies heavily on this agent**, which continuously
refines the top-ranked hypotheses emerging from the tournament." The measured
improvement in the paper (Figure 4: best-hypothesis Elo rising ~1350 → ~1610
with test-time compute) is produced by the loop

    Generation → Reflection → Ranking (Elo tournament) → Evolution → Meta-review

— NOT by meta-review feedback alone, which is what A.M.Y's earlier learning
ablation tested (and correctly found indistinguishable from noise).

Paper-faithful design constraints implemented here:
- "The Evolution agent generates NEW hypotheses; it doesn't modify or replace
  existing ones." Evolved candidates are new entrants that must compete in the
  tournament (initial Elo 1200, per §3.3.3).
- Refinement strategies from §3.3.5: enhancement through grounding;
  coherence/practicality/feasibility improvements; inspiration from existing
  hypotheses; combination; simplification; out-of-box thinking.
- Meta-review feedback propagation (§3.3.6): when a feedback digest is supplied,
  it is appended to the evolution prompt so recurring weaknesses are pre-empted
  in the next generation of hypotheses.

LLM-backed with a deterministic fallback, mirroring the rest of A.M.Y: the
fallback sharpens the parent hypothesis with an explicit, concrete test
procedure (genuinely raising falsifiability/specificity — the dimensions the
tournament judge measures), so the loop still functions without an API key and
tests stay hermetic.
"""
from __future__ import annotations

import asyncio
import json
import os
import re

import structlog

log = structlog.get_logger()

STRATEGIES = ("grounding", "feasibility", "combination", "simplification", "out_of_box")

_STRATEGY_INSTRUCTIONS = {
    "grounding": (
        "Improve the hypothesis by IDENTIFYING ITS WEAKNESSES and filling reasoning "
        "gaps with concrete details: name the exact quantities to measure, the ranges "
        "to scan, and the comparison baseline. (Co-Scientist 'enhancement through "
        "grounding'.)"
    ),
    "feasibility": (
        "Rewrite the hypothesis to be MORE PRACTICAL AND FEASIBLE to test with "
        "standard computational tools (SymPy/NumPy/PySCF-class), fixing any invalid "
        "assumptions. (Co-Scientist 'coherence, practicality and feasibility'.)"
    ),
    "combination": (
        "COMBINE the best aspects of the two hypotheses below into one stronger, "
        "testable hypothesis. (Co-Scientist 'combination'.)"
    ),
    "simplification": (
        "SIMPLIFY the hypothesis so it is easier to verify and test, while keeping "
        "its core claim falsifiable and specific. (Co-Scientist 'simplification'.)"
    ),
    "out_of_box": (
        "Generate a DIVERGENT hypothesis inspired by — but deliberately departing "
        "from — the one below: explore an unexplored angle of the same evidence. "
        "(Co-Scientist 'out-of-box thinking'.)"
    ),
}

EVOLUTION_PROMPT = """You are the Evolution agent of an AI co-scientist (Google Co-Scientist pattern). Your job: produce ONE new, improved research hypothesis.

{strategy_instruction}

Domain: {domain}
Computational evidence available to ground claims (the only evidence that exists):
{evidence}

Parent hypothesis (Elo {parent_elo:.0f}, tournament record {parent_record}):
{parent}
{second_parent_block}
Requirements for the evolved hypothesis:
1. It must be FALSIFIABLE: include an explicit test with named quantities, thresholds or ranges, and a comparison baseline ("Testable via: ...").
2. It must be SPECIFIC: numbers, ranges, named methods — no vague claims.
3. It must stay consistent with the evidence above (do not invent measured values).
4. It must be genuinely DIFFERENT from the parent (an improvement or a new angle, not a paraphrase).
{feedback_block}
Output STRICTLY one JSON object, nothing else:
{{"hypothesis": "<one or two sentences, ending with 'Testable via: <concrete procedure>'>", "rationale": "<one sentence: what was improved>"}}"""


def _format_evidence(results: list[dict] | None, limit: int = 6) -> str:
    if not results:
        return "(no tool results supplied)"
    lines = []
    for r in results[:limit]:
        desc = r.get("description", "")
        out = str(r.get("result", ""))[:300]
        lines.append(f"- {desc}: {out}")
    return "\n".join(lines)


def _build_client():
    from core.ollama_client import OllamaCloudClient
    cfg = {"base_url": "https://ollama.com/api"}
    try:
        import yaml
        cfg_path = os.path.join(os.path.dirname(__file__), "..", "config.yaml")
        with open(cfg_path) as f:
            full = yaml.safe_load(f) or {}
        if full.get("llm", {}).get("base_url"):
            cfg["base_url"] = full["llm"]["base_url"]
    except Exception:
        pass
    return OllamaCloudClient(cfg)


def _resolve_model() -> str:
    model = os.getenv("AMY_EVOLUTION_MODEL")
    if model:
        return model
    try:
        import yaml
        cfg_path = os.path.join(os.path.dirname(__file__), "..", "config.yaml")
        with open(cfg_path) as f:
            cfg = yaml.safe_load(f) or {}
        return cfg.get("llm", {}).get("reasoner", {}).get("model", "glm-5.1")
    except Exception:
        return "glm-5.1"


def deterministic_evolve(parent: dict, strategy: str, second_parent: dict | None = None,
                         feedback: str | None = None, domain: str = "",
                         results: list[dict] | None = None) -> dict:
    """LLM-free fallback: sharpen the parent with a concrete test procedure.

    This genuinely raises falsifiability/specificity (the tournament judge's
    criteria) rather than gaming string length: it appends a structured,
    quantity-named test when one is missing, or tightens it when present.

    ``feedback`` is CONSUMED here too (the earlier version ignored it, which
    silently disconnected the meta-review loop whenever the LLM path failed —
    caught by the adversarial verifiers as 'full ≡ evolution to the last
    decimal'). Feedback-mentioned weaknesses trigger targeted sharpening.
    """
    text = parent.get("hypothesis", "").strip().rstrip(".")
    if strategy == "combination" and second_parent:
        text2 = second_parent.get("hypothesis", "").split("Testable via:")[0].strip().rstrip(".")
        base = text.split("Testable via:")[0].strip().rstrip(".")
        if text2:
            # text2[:1] (not text2[0]) so an empty second hypothesis — or one
            # that was only a "Testable via:" clause — can't IndexError in this
            # supposedly-always-safe fallback.
            new_text = f"{base}; moreover, {text2[:1].lower()}{text2[1:]}"
        else:
            new_text = base
    elif strategy == "simplification":
        base = text.split("Testable via:")[0].strip().rstrip(".")
        # Keep the first clause only.
        new_text = re.split(r"[;,] ", base, maxsplit=1)[0]
    else:
        new_text = text.split("Testable via:")[0].strip().rstrip(".")

    fb = (feedback or "").lower()
    test_clause = (
        ". Testable via: compute the quantity across at least 3 independent "
        "parameter ranges, report effect size with 95% confidence intervals, "
        "and compare against the published baseline; predict the deviation "
        "exceeds 2 standard errors in the largest range."
    )
    context = " ".join(
        [
            domain.lower(),
            new_text.lower(),
            str(parent.get("method", "")).lower(),
            " ".join(str(r.get("tool", "")).lower() for r in (results or [])),
        ]
    )
    if "chemistry" in context and ("ssh_" in context or "edge-state" in context or "polyene" in context):
        test_clause = (
            ". Testable via: rerun ssh_edge_localization_map and "
            "ssh_polyene_gap_map on denser chain lengths and a denser delta "
            "grid; require the topological edge weight/IPR localization signal, "
            "localization_onset_n, and edge_state_onset_n to remain ordered "
            "relative to the trivial-orientation controls."
        )
    # Feedback-driven sharpening (causal consumption of the meta-review digest):
    if "falsifia" in fb or "test procedure" in fb:
        if "chemistry" in context and ("ssh_" in context or "edge-state" in context or "polyene" in context):
            test_clause = (
                ". Testable via: pre-register the SSH chain lengths, delta grid, "
                "edge_sites, and localization_threshold; rerun "
                "ssh_edge_localization_map with the fixed script, and reject the "
                "hypothesis if topological frontier states do not retain higher "
                "edge weight/IPR and lower participation_sites than the matched "
                "trivial controls."
            )
        else:
            test_clause = (
                ". Testable via: pre-register the predicted direction and magnitude, "
                "measure the named quantity across at least 5 parameter ranges with a "
                "fixed analysis script, report effect size with 95% confidence "
                "intervals against the published baseline, and reject the hypothesis "
                "if the deviation is below 2 standard errors in every range."
            )
    if ("vague" in fb or "quantities" in fb) and not re.search(r"\d", new_text):
        new_text += " (predicted effect: a monotonic shift exceeding 5% across one decade of scale)"
    if "known control" in fb or "textbook" in fb:
        new_text = re.sub(r"^(The|Our|This)\b", "Departing from the known baseline, \\1".replace("\\1", "the"),
                          new_text, count=1) if new_text else new_text

    if "testable via:" not in new_text.lower():
        new_text += test_clause
    method = new_text.split("Testable via:", 1)[-1].strip() if "testable via:" in new_text.lower() else ""
    return {
        "hypothesis": new_text,
        "novelty_status": parent.get("novelty_status", "testable_hypothesis"),
        "confidence": min(0.9, float(parent.get("confidence", 0.5)) + 0.05),
        "method": method or parent.get("method", ""),
        "evolved_from": parent.get("hypothesis", "")[:80],
        "strategy": strategy,
        "evolver": "deterministic",
        "feedback_applied": bool(fb),
    }


async def evolve_hypothesis(
    parent: dict,
    strategy: str = "grounding",
    domain: str = "",
    results: list[dict] | None = None,
    second_parent: dict | None = None,
    feedback: str | None = None,
    client=None,
    model: str | None = None,
    timeout: float = 60.0,
) -> dict:
    """Produce ONE new evolved hypothesis (paper: a new entrant, parent unchanged).

    Falls back to ``deterministic_evolve`` on any LLM failure.
    """
    if strategy not in STRATEGIES:
        strategy = "grounding"

    if client is None:
        try:
            client = _build_client()
        except Exception:
            return deterministic_evolve(
                parent,
                strategy,
                second_parent,
                feedback=feedback,
                domain=domain,
                results=results,
            )

    second_block = ""
    if strategy == "combination" and second_parent:
        second_block = (f"\nSecond parent hypothesis (Elo "
                        f"{second_parent.get('elo', 1200):.0f}):\n"
                        f"{second_parent.get('hypothesis', '')}\n")

    feedback_block = ""
    if feedback and feedback.strip():
        feedback_block = (
            "\nMeta-review feedback from prior tournament cycles (recurring "
            "weaknesses to pre-empt — apply it):\n" + feedback.strip() + "\n"
        )

    prompt = EVOLUTION_PROMPT.format(
        strategy_instruction=_STRATEGY_INSTRUCTIONS[strategy],
        domain=domain or parent.get("domain", "science"),
        evidence=_format_evidence(results),
        parent=parent.get("hypothesis", ""),
        parent_elo=float(parent.get("elo", 1200.0)),
        parent_record=parent.get("tournament_record", "0W-0L-0D"),
        second_parent_block=second_block,
        feedback_block=feedback_block,
    )

    # Root cause of the prior silent-degradation incident: glm-5.1 is a
    # *thinking* model — with format_json it burned the whole num_predict
    # budget on its hidden reasoning trace and returned EMPTY content (we
    # measured eval_count == max_tokens, thinking 9k chars, content 7 chars).
    # Fix: think=False (verified supported by Ollama Cloud), a salvage parse
    # from the thinking trace, and one retry before falling back.
    last_err = None
    for attempt in range(2):
        try:
            resp = await asyncio.wait_for(
                client.chat(model=model or _resolve_model(),
                            messages=[{"role": "user", "content": prompt}],
                            temperature=0.7, max_tokens=900, format_json=True,
                            think=False),
                timeout=timeout,
            )
            msg = resp.get("message", {}) or {}
            content = (msg.get("content") or "").strip()
            if content.startswith("```"):
                content = content.strip("`").lstrip("json").strip()
            if not content and msg.get("thinking"):
                # Salvage: thinking models sometimes finish the JSON inside the
                # trace. Take the last {...} block found there.
                blocks = re.findall(r"\{[^{}]*\"hypothesis\"[^{}]*\}", msg["thinking"], re.DOTALL)
                if blocks:
                    content = blocks[-1]
            data = json.loads(content)
            text = str(data.get("hypothesis", "")).strip()
            if len(text) < 40:
                raise ValueError("evolved hypothesis too short")
            # Extract an explicit test procedure into 'method' (downstream
            # conclusion-builder cites it). Prefer the 'Testable via:' clause.
            method = ""
            if "testable via:" in text.lower():
                method = text.split("Testable via:", 1)[-1].strip()
            child = {
                "hypothesis": text,
                "novelty_status": parent.get("novelty_status", "testable_hypothesis"),
                "confidence": float(parent.get("confidence", 0.5)),
                "method": method or parent.get("method", ""),
                "evolved_from": parent.get("hypothesis", "")[:80],
                "strategy": strategy,
                "rationale": str(data.get("rationale", ""))[:200],
                "evolver": "llm",
            }
            log.info("evolution_agent.evolved", strategy=strategy, chars=len(text))
            return child
        except Exception as exc:
            last_err = exc
            if attempt == 0:
                await asyncio.sleep(2.0)

    log.warning("evolution_agent.fallback", strategy=strategy, error=str(last_err)[:120])
    return deterministic_evolve(
        parent,
        strategy,
        second_parent,
        feedback=feedback,
        domain=domain,
        results=results,
    )
