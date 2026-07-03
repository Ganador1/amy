#!/usr/bin/env python3
"""Benchmark Ollama Cloud models for A.M.Y's reasoning workload.

For each model we send the *real* reasoning prompt the heartbeat would send
(a ~2000-token system+task prompt asking for a JSON action decision) with a
generous max_tokens budget, and we measure:

  - wall-clock latency,
  - whether the reply is parseable JSON with a valid action_type,
  - eval_count / thinking length (how much the model "thinks"),
  - failures / timeouts.

Models that answer fast AND emit valid action JSON are good drivers for the
autonomous loop. "Thinking" models that stream for >60s are flagged as
impractical for the heartbeat even if their output is good.

Usage:
    .venv/bin/python scripts/diagnostics/benchmark_models.py
    .venv/bin/python scripts/diagnostics/benchmark_models.py --models gpt-oss:120b,qwen3-coder:480b
    .venv/bin/python scripts/diagnostics/benchmark_models.py --max-tokens 16384 --timeout 90
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from core.ollama_client import OllamaCloudClient  # noqa: E402

# A representative slice of the 41 cloud models, chosen for the agentic loop:
# fast non-thinking coders + a few strong reasoners for comparison.
DEFAULT_MODELS = [
    "glm-5.2",
    "kimi-k2.7-code",
    "gpt-oss:20b",
    "gpt-oss:120b",
    "qwen3-coder-next",
    "qwen3-coder:480b",
    "gemini-3-flash-preview",
    "minimax-m2.7",
    "minimax-m3",
    "deepseek-v3.1:671b",
]

# The real reasoning prompt shape (condensed but same structure/size class).
SYSTEM_PROMPT = (
    "You are A.M.Y (Autonomous Mind Yield), an autonomous scientific research "
    "agent. You think in cycles: perceive, decide an action, act, learn. "
    "On each cycle you output ONE JSON object describing your next action.\n\n"
    "Available action_type values:\n"
    "- run_scientific_tool: invoke an Atlas tool (sympy, numpy, prime analysis...)\n"
    "- experiment: write and run Python in a sandbox to test a hypothesis\n"
    "- search_literature: query open scholarly databases\n"
    "- write_paper: synthesize findings into an academic paper\n"
    "- decompose_goal: break the goal into sub-goals\n\n"
    "Output schema (JSON ONLY, no prose):\n"
    '{"action_type": "...", "content": "<1-3 sentence rationale>", '
    '"action_details": {"tool_name": "...", "tool_input": "...", '
    '"hypothesis": "...", "research_query": "..."}}\n\n'
    "Rules: experiments before papers; every numeric claim must come from a "
    "real tool or experiment; be specific; never fabricate data. "
) + ("Background context for grounding. " * 60)  # pad to ~reasoning size

TASK_PROMPT = (
    "Current mission goal: Investigate whether the distribution of gaps between "
    "consecutive prime numbers follows an exponential law or shows systematic "
    "deviations from it.\n"
    "Recent cycle history: (none yet — this is cycle 0).\n"
    "Decide your single next action now as JSON."
)


async def bench_one(client, model, max_tokens, timeout):
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": TASK_PROMPT},
    ]
    t0 = time.monotonic()
    try:
        resp = await asyncio.wait_for(
            client.chat(model=model, messages=messages, temperature=0.3,
                        max_tokens=max_tokens, format_json=True, num_ctx=32768),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        return {"model": model, "status": "TIMEOUT", "elapsed": time.monotonic() - t0}
    except Exception as e:  # noqa: BLE001
        return {"model": model, "status": f"FAIL:{type(e).__name__}",
                "elapsed": time.monotonic() - t0, "err": str(e)[:120]}

    dt = time.monotonic() - t0
    msg = resp.get("message", {})
    content = msg.get("content", "") or ""
    thinking = msg.get("thinking", "") or ""
    # If content empty, the model spent its budget thinking.
    body = content if content.strip() else thinking

    # Try to parse an action_type out of it.
    action = None
    valid_json = False
    try:
        start, end = body.find("{"), body.rfind("}")
        if start >= 0 and end > start:
            obj = json.loads(body[start:end + 1])
            valid_json = True
            action = obj.get("action_type")
    except Exception:
        pass

    return {
        "model": model,
        "status": "OK",
        "elapsed": dt,
        "eval_count": resp.get("eval_count"),
        "think_len": len(thinking),
        "content_len": len(content),
        "valid_json": valid_json,
        "action_type": action,
    }


async def main_async(models, max_tokens, timeout):
    client = OllamaCloudClient({"base_url": "https://ollama.com/api",
                                "read_timeout": timeout + 10,
                                "total_timeout": timeout})
    print(f"Benchmarking {len(models)} models | max_tokens={max_tokens} "
          f"| per-model timeout={timeout}s")
    print("=" * 92)
    print(f"{'model':24} {'status':14} {'secs':>6} {'eval':>6} "
          f"{'think':>6} {'json':>5} {'action_type':>20}")
    print("-" * 92)
    rows = []
    # Sequential so we don't create cross-model rate-limit contention.
    for m in models:
        r = await bench_one(client, m, max_tokens, timeout)
        rows.append(r)
        secs = f"{r['elapsed']:.1f}"
        if r["status"] == "OK":
            print(f"{m:24} {'OK':14} {secs:>6} "
                  f"{str(r.get('eval_count','')):>6} {str(r.get('think_len','')):>6} "
                  f"{str(r.get('valid_json')):>5} {str(r.get('action_type'))[:20]:>20}")
        else:
            print(f"{m:24} {r['status']:14} {secs:>6}")
    await client.close()

    print("=" * 92)
    ok = [r for r in rows if r["status"] == "OK" and r.get("valid_json")]
    ok.sort(key=lambda r: r["elapsed"])
    print(f"\nUSABLE for the heartbeat (valid JSON action), fastest first:")
    for r in ok:
        print(f"  {r['model']:24} {r['elapsed']:5.1f}s  action={r['action_type']}")
    if not ok:
        print("  (none returned valid action JSON within the timeout)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", type=str, default=None,
                    help="comma-separated model tags; default = curated list")
    ap.add_argument("--max-tokens", type=int, default=8192)
    ap.add_argument("--timeout", type=float, default=75.0)
    args = ap.parse_args()
    models = args.models.split(",") if args.models else DEFAULT_MODELS
    return asyncio.run(main_async([m.strip() for m in models],
                                  args.max_tokens, args.timeout))


if __name__ == "__main__":
    raise SystemExit(main())
