"""Compare modes across result directories, split into cold and warm runs.

    uv run python scripts/compare.py results/A results/B ... [--repeats 1,2] [--tasks prefix]

Repeat 1 of a task is a cold prompt cache (what a real session pays); later
repeats are warm. Medians, because a few long diagnosis runs skew means.
"""
from __future__ import annotations

import json
import statistics as st
import sys
from pathlib import Path


def ctx(r: dict) -> int:
    u = r.get("usage", {})
    return u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0) + u.get("cache_creation_input_tokens", 0)


def startup_from_events(path: Path) -> int:
    """Context on the first model call, for runs recorded before the harness kept it."""
    if not path.exists():
        return 0
    for line in path.read_text(encoding="utf-8").splitlines():
        ev = json.loads(line)
        if ev.get("type") == "assistant":
            u = (ev.get("message") or {}).get("usage") or {}
            return sum(int(u.get(k, 0) or 0) for k in
                       ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
    return 0


def main() -> int:
    dirs = [Path(a) for a in sys.argv[1:] if not a.startswith("--")]
    opts = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--") and "=" in a)
    reps = {int(x) for x in opts.get("repeats", "1,2,3").split(",")}
    prefix = opts.get("tasks", "")
    rows = []
    for d in dirs:
        for p in sorted(d.glob("*.json")):
            if p.name == "run.json":
                continue
            r = json.loads(p.read_text())
            if not r.get("startup_tokens"):
                r["startup_tokens"] = startup_from_events(p.with_name(p.stem + ".events.jsonl"))
            if r["repeat"] in reps and r["task"].startswith(prefix):
                rows.append(r)
    modes = sorted({r["mode"] for r in rows}, key=["full", "preset", "gateway", "catalog"].index)
    med = lambda xs: st.median(xs) if xs else 0
    print("| Mode | Runs | Passed | Median turns | Startup context | Context per run | Cold cost | Warm cost | Total cost | Precision | Recall |")
    print("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    for m in modes:
        rs = [r for r in rows if r["mode"] == m]
        cold = [r["cost_usd"] for r in rs if r["repeat"] == 1]
        warm = [r["cost_usd"] for r in rs if r["repeat"] > 1]
        start = [r.get("startup_tokens") for r in rs if r.get("startup_tokens")]
        print(f"| {m} | {len(rs)} | {sum(r['passed'] for r in rs)} | {med([r['num_turns'] for r in rs])} "
              f"| {f'{med(start):,.0f}' if start else 'n/a'} | {med([ctx(r) for r in rs]):,.0f} "
              f"| ${med(cold):.3f} | ${med(warm):.3f} | ${sum(r['cost_usd'] for r in rs):.2f} "
              f"| {st.mean(r['tool_precision'] for r in rs):.2f} | {st.mean(r['tool_recall'] for r in rs):.2f} |")
    fails = [r for r in rows if not r["passed"]]
    if fails:
        print("\nFailures:")
        for r in fails:
            why = "; ".join(f"{c['name']}: {c['detail']}" for c in r["checks"] if not c["passed"] and not c.get("soft"))
            print(f"- {r['mode']} {r['task']} rep {r['repeat']}: {why or r.get('subtype')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
