#!/usr/bin/env python3
"""
Longevity monitor — tests the README claim that A.M.Y "can be live indefinitely".

Launches the real heartbeat loop (amy.py) as a subprocess and samples, every
INTERVAL seconds: wall-clock elapsed, the process RSS (memory), and the latest
cycle number parsed from A.M.Y's own structured logs. Writes a time-series so we
can answer: does it survive, is memory bounded, do cycles keep advancing, does it
recover from per-cycle errors?

Run:
    .venv/bin/python scripts/diagnostics/longevity_monitor.py --minutes 20
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def rss_mb(pid: int) -> float | None:
    """Resident set size in MB for the process tree (ps, macOS-friendly)."""
    try:
        out = subprocess.check_output(["ps", "-o", "rss=", "-p", str(pid)], text=True)
        return round(int(out.strip()) / 1024.0, 1)
    except Exception:
        return None


def latest_cycle(log_path: Path) -> int:
    """Parse the highest cycle number A.M.Y has logged so far."""
    try:
        text = log_path.read_text(errors="ignore")
    except Exception:
        return -1
    cycles = re.findall(r"cycle=(\d+)", text)
    return max((int(c) for c in cycles), default=-1)


def count_errors(log_path: Path) -> int:
    try:
        return log_path.read_text(errors="ignore").count("heartbeat.cycle_error")
    except Exception:
        return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=20.0)
    ap.add_argument("--sample-every", type=float, default=30.0, help="seconds")
    ap.add_argument("--goal", default="", help="empty = no predefined goal (curiosity-driven)")
    ap.add_argument("--config", default="/tmp/amy_fast_config.yaml")
    args = ap.parse_args()

    out_dir = ROOT / "experiments" / "e2e_v2"
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / "amy_live.log"
    series_path = out_dir / "longevity_series.json"

    venv_py = str(ROOT / ".venv" / "bin" / "python")
    cmd = [venv_py, "amy.py", "--config", args.config]
    if args.goal.strip():
        cmd += ["--goal", args.goal]
    log_f = open(log_path, "w")
    proc = subprocess.Popen(cmd, cwd=str(ROOT), stdout=log_f, stderr=subprocess.STDOUT)
    goal_desc = repr(args.goal) if args.goal.strip() else "(none — curiosity-driven)"
    print(f"Launched A.M.Y (pid {proc.pid}) goal={goal_desc}; "
          f"monitoring {args.minutes} min → {series_path}")

    samples = []
    t0 = time.monotonic()
    deadline = t0 + args.minutes * 60
    first_rss = None
    try:
        while time.monotonic() < deadline:
            time.sleep(args.sample_every)
            alive = proc.poll() is None
            rss = rss_mb(proc.pid) if alive else None
            cyc = latest_cycle(log_path)
            errs = count_errors(log_path)
            elapsed = round(time.monotonic() - t0, 1)
            if rss is not None and first_rss is None:
                first_rss = rss
            sample = {"t_s": elapsed, "alive": alive, "rss_mb": rss,
                      "cycle": cyc, "cycle_errors": errs}
            samples.append(sample)
            growth = f"+{round(rss - first_rss, 1)}MB" if (rss and first_rss) else "?"
            print(f"  t={elapsed:6.0f}s alive={alive} rss={rss}MB ({growth}) "
                  f"cycle={cyc} errors={errs}")
            if not alive:
                print(f"  !! A.M.Y exited (returncode {proc.returncode}) at t={elapsed}s")
                break
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                proc.kill()
        log_f.close()

    # Verdict summary.
    rss_vals = [s["rss_mb"] for s in samples if s["rss_mb"]]
    cyc_vals = [s["cycle"] for s in samples if s["cycle"] >= 0]
    summary = {
        "minutes_requested": args.minutes,
        "samples": len(samples),
        "survived_whole_run": bool(samples and samples[-1]["alive"]),
        "cycles_reached": max(cyc_vals, default=-1),
        "cycles_advanced": (len(set(cyc_vals)) > 1),
        "total_cycle_errors": samples[-1]["cycle_errors"] if samples else 0,
        "rss_first_mb": rss_vals[0] if rss_vals else None,
        "rss_last_mb": rss_vals[-1] if rss_vals else None,
        "rss_max_mb": max(rss_vals, default=None),
        "rss_growth_mb": round(rss_vals[-1] - rss_vals[0], 1) if len(rss_vals) >= 2 else None,
    }
    (series_path).write_text(json.dumps({"summary": summary, "samples": samples}, indent=2))
    print("\n=== LONGEVITY SUMMARY ===")
    for k, v in summary.items():
        print(f"  {k}: {v}")
    print(f"\nSeries: {series_path}\nLog: {log_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
