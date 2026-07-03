# Longevity test — does A.M.Y "run live indefinitely"?

The README's design philosophy says A.M.Y "never sleeps. With no urgent task, it
reflects, consolidates memory, or explores out of curiosity" and "the heartbeat
loop runs indefinitely... until the OS kills it." This is the empirical test of
that claim.

## Method

Ran the real `amy.py` heartbeat loop for **60 minutes with NO predefined goal**
(`mission.goal = ""`) — the strongest form of the claim, forcing A.M.Y to sustain
itself by curiosity alone. `scripts/diagnostics/longevity_monitor.py` sampled the
process RSS, the latest cycle number, and the cumulative cycle-error count every
30 s (120 samples). Cycle pacing is LLM/network-bound (~12 s/cycle), not the
config interval.

## Results

| Criterion | Result |
|---|---|
| Survived the full hour | **Yes** — `alive=True` across all 120 samples |
| Cycles advanced | **Yes** — reached cycle **90**, monotonically |
| Memory bounded | **Yes** — RSS **66.5 → 57.0 MB** (net **−9.5 MB**), max 74.6 MB |
| Recovered from per-cycle errors | **Yes** — **0** uncaught `heartbeat.cycle_error`, 0 tracebacks |

**Memory is the decisive metric.** A process that "runs indefinitely" must not leak.
RSS did not grow — it oscillated in a stable ~56–75 MB band and ended *below* where
it started. This matches the architecture review: every in-memory accumulator is
capped (`thoughts ≤100`, `_recent_queries ≤20`, `_recent_hypotheses ≤15`,
`_tool_results_history ≤20`, episodic `_buffer ≤500`), and the loop wraps each beat
in `try/except` so a bad cycle is logged and skipped, not fatal.

## It was genuinely working, not idling

Over 90 cycles A.M.Y took **75 substantive actions**: 47 `experiment`, 24
`search_literature`, 3 `think_more`, 1 `research` — **47 experiments completed**
with provenance, and **13 reflection/consolidation events**. The 16 warnings were
all Semantic Scholar HTTP 429 rate-limits, every one handled gracefully (none
escalated to a cycle error).

With no goal, it self-generated a coherent research arc by curiosity: explored
whether biological information processing can beat the sub-Landauer thermodynamic
limit → formed quantitative hypotheses about neural energy cost per operation →
paused to verify against literature → returned to deep mathematical reasoning. A
stuck loop would repeat one cheap action; this is a real investigation.

## Verdict

**The "runs indefinitely" claim is empirically supported.** Over a real 60-minute
curiosity-driven run: bounded (even slightly decreasing) memory, monotonic cycle
progress, zero crashes, graceful recovery from transient API failures, and genuine
research work throughout. The architecture's bounded buffers + per-cycle error
isolation are the mechanism; the flat memory curve is the proof.

**Honest caveats.** (1) 60 minutes / 90 cycles is strong evidence but not literally
"forever" — a multi-day run could still surface slow effects (disk growth in
`data/experiments/`, log-file size). (2) Throughput depends on the Ollama Cloud
API; if the key is exhausted the loop keeps running but does no LLM work. (3) The
on-disk episodic buffer is capped in memory (500), but provenance files and logs
accumulate on disk and would need rotation for a truly unbounded deployment.

*Series: `experiments/e2e_v2/longevity_series.json`; raw log: `amy_live.log`.*
