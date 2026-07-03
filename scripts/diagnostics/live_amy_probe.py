#!/usr/bin/env python3
"""Live probe of A.M.Y: run real cognitive cycles and observe behaviour.

This is NOT a unit test — it spins up the *full* A.M.Y stack (real Ollama
LLM, real Atlas tools, real Docker sandbox) and runs a bounded number of
`Heartbeat._beat()` cycles, logging every decision so we can see:

  - what A.M.Y chooses to focus on each cycle,
  - which action_type she picks (run_scientific_tool, experiment, ...),
  - whether tool calls actually reach Atlas and return real data,
  - how curiosity / goals drive her when left to her own devices.

Usage:
    .venv/bin/python scripts/diagnostics/live_amy_probe.py --cycles 5
    .venv/bin/python scripts/diagnostics/live_amy_probe.py --cycles 8 --goal "..."
    .venv/bin/python scripts/diagnostics/live_amy_probe.py --cycles 10 --no-goal

--no-goal sets an open-ended "follow your curiosity" mission so we can watch
autonomous goal formation.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.chdir(ROOT)

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

import yaml  # noqa: E402

from amy import AMY  # noqa: E402


OPEN_ENDED_GOAL = "Explorar libremente cualquier pregunta científica que despierte tu curiosidad"
OPEN_ENDED_DESC = (
    "No tienes un objetivo fijo. Observa, genera tus propias preguntas, "
    "usa las herramientas científicas disponibles, ejecuta experimentos y "
    "decide tú misma qué vale la pena investigar."
)


def _new_tool_results(history, start_index: int) -> list[dict]:
    """Return tool results appended after start_index for list/deque histories."""
    items = list(history)
    if start_index < 0:
        start_index = 0
    if start_index > len(items):
        return []
    return items[start_index:]


def _summarize_result(res) -> str:
    if res is None:
        return "(none)"
    if isinstance(res, dict):
        # common shapes
        for k in ("summary", "result", "stdout", "content", "status"):
            if k in res and res[k]:
                return f"{k}={str(res[k])[:160]}"
        return json.dumps(res, default=str)[:160]
    return str(res)[:160]


async def probe(cycles: int, goal: str | None, open_ended: bool, verbose: bool,
                config_path: str = "config.yaml", cycle_timeout: float = 150.0) -> int:
    with open(config_path) as f:
        config = yaml.safe_load(f)
    print(f"  config: {config_path}")
    print(f"  reasoner model: {config['llm']['reasoner']['model']}")

    if open_ended:
        config["mission"]["goal"] = OPEN_ENDED_GOAL
        config["mission"]["description"] = OPEN_ENDED_DESC
    elif goal:
        config["mission"]["goal"] = goal

    # Run cycles back-to-back (no sleeping between them) for the probe.
    config["heartbeat"]["base_interval_seconds"] = 0
    config["heartbeat"]["idle_interval_seconds"] = 0
    config["heartbeat"]["focused_interval_seconds"] = 0

    print("=" * 80)
    print(f"A.M.Y LIVE PROBE — {cycles} cycles")
    print(f"  mission goal: {config['mission']['goal']}")
    print(f"  open-ended  : {open_ended}")
    print("=" * 80)

    amy = AMY(config)
    hb = amy.heartbeat

    # Seed the goal stack just like AMY.start() does.
    await amy.goal_stack.set_mission(
        goal=config["mission"]["goal"],
        description=config["mission"].get("description", ""),
    )

    timeline = []
    tools_seen: list[tuple[int, str, str]] = []

    for i in range(1, cycles + 1):
        hb.ctx.cycle_number = i
        t0 = time.monotonic()
        n_tools_before = len(hb._tool_results_history)

        try:
            # Hard per-cycle deadline so a slow/queued LLM call can't hang the
            # whole run — the cycle is skipped and we move on. Newer cloud
            # models (e.g. minimax-m3) have very variable latency.
            await asyncio.wait_for(hb._beat(), timeout=cycle_timeout)
            err = None
        except asyncio.TimeoutError:
            err = f"cycle timeout >{cycle_timeout}s (LLM too slow this cycle)"
        except Exception as e:  # keep probing even if one cycle fails
            err = f"{type(e).__name__}: {e}"

        dt = time.monotonic() - t0
        focus = (hb.ctx.current_focus or "")[:70]
        action = getattr(hb, "_last_action_type", "?")

        # Any new tool results this cycle?
        new_tools = _new_tool_results(hb._tool_results_history, n_tools_before)
        for tr in new_tools:
            tname = tr.get("tool") or tr.get("tool_name") or "?"
            tout = str(tr.get("result") or tr.get("output") or tr.get("raw") or tr)[:120]
            tools_seen.append((i, str(tname), tout))

        timeline.append((i, action, focus, len(new_tools), dt, err))

        status = "ERR" if err else "ok"
        print(f"\n── cycle {i:2}/{cycles}  [{status}]  {dt:5.1f}s  "
              f"action={action!r}  tools+={len(new_tools)}")
        print(f"     focus: {focus}")
        if new_tools:
            for tr in new_tools:
                tname = tr.get("tool") or tr.get("tool_name") or "?"
                print(f"     tool→ {tname}: {_summarize_result(tr)[:140]}")
        if err:
            print(f"     error: {err}")

    await hb.stop()

    # ── Summary ──────────────────────────────────────────────────────────
    print("\n" + "=" * 80)
    print("PROBE SUMMARY")
    print("=" * 80)
    from collections import Counter
    action_counts = Counter(t[1] for t in timeline)
    print("action_type distribution:")
    for a, c in action_counts.most_common():
        print(f"   {a:24} ×{c}")
    n_err = sum(1 for t in timeline if t[5])
    print(f"cycles ok: {cycles - n_err}/{cycles}")
    print(f"total tool calls reaching Atlas: {len(tools_seen)}")
    for cyc, tname, tout in tools_seen:
        print(f"   c{cyc}: {tname} → {tout}")

    # Inspect goal stack evolution (autonomy signal)
    try:
        active = await amy.goal_stack.get_active_goals()
        print(f"active goals after probe: {len(active)}")
        for g in active[:6]:
            desc = g.get("goal") if isinstance(g, dict) else getattr(g, "goal", str(g))
            print(f"   - {str(desc)[:80]}")
    except Exception as e:
        print(f"(could not read goal stack: {e})")

    return 0 if n_err < cycles else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cycles", type=int, default=5)
    ap.add_argument("--goal", type=str, default=None)
    ap.add_argument("--no-goal", action="store_true",
                    help="open-ended mission to observe autonomous goal formation")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--config", type=str, default="config.yaml")
    ap.add_argument("--cycle-timeout", type=float, default=150.0,
                    help="hard per-cycle deadline in seconds")
    args = ap.parse_args()
    return asyncio.run(
        probe(args.cycles, args.goal, args.no_goal, args.verbose, args.config,
              args.cycle_timeout))


if __name__ == "__main__":
    raise SystemExit(main())
