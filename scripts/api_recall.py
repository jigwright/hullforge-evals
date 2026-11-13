"""Measure hf_api_lookup retrieval against api/gold.toml (or --set heldout), offline.

    uv run python scripts/api_recall.py            # all three methods
    uv run python scripts/api_recall.py --show     # also print each miss

Builds (or loads the cached) index from the newest installed engine, the same
way the connector does, then asks every gold question three ways: keywords
only (BM25), embeddings only, and hybrid (both, fused by reciprocal rank).
Reports recall@1, recall@5 and MRR@10 overall and per answer kind, and writes
results/api_recall.json.
"""
from __future__ import annotations

import argparse
import json
import time
import tomllib
from pathlib import Path

from hullforge_mcp import api_index as ai

ROOT = Path(__file__).resolve().parents[1]
METHODS = ("bm25", "embedding", "hybrid")


def matches(record: ai.Record, want: str) -> bool:
    for option in want.split("|"):
        if option.startswith("note~"):
            if record.kind == "note" and option[5:].lower() in record.name.lower():
                return True
        elif record.name == option:
            return True
    return False


def category(want: str, index: ai.ApiIndex) -> str:
    first = want.split("|")[0]
    if first.startswith("note~"):
        return "note"
    for r in index.records:
        if r.name == first:
            return r.kind
    return "missing"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--set", default="gold", choices=["gold", "heldout"],
                    help="gold = the dev set used while tuning; heldout = questions tuning never saw")
    args = ap.parse_args()

    gold = tomllib.loads((ROOT / "api" / f"{args.set}.toml").read_text(encoding="utf-8"))["q"]
    engine = ai.pick_engine(ai.find_engines())
    t = time.time()
    index = ai.build_index(engine)
    index.build_embeddings()
    print(f"UE {index.status.engine}: {len(index.records)} entries, embeddings {index.status.embeddings}, "
          f"ready in {time.time() - t:.1f}s")

    missing = [q["want"] for q in gold if category(q["want"], index) == "missing"]
    if missing:
        raise SystemExit(f"gold answers not in the index: {missing}")

    results: dict[str, dict] = {}
    per_query: list[dict] = []
    for method in METHODS:
        hits1 = hits5 = 0
        rr = 0.0
        by_kind: dict[str, list[int]] = {}
        latencies = []
        for q in gold:
            s = time.perf_counter()
            ranked = [r for _, r in index.search(q["query"], method=method, limit=10)]
            latencies.append(time.perf_counter() - s)
            rank = next((i + 1 for i, r in enumerate(ranked) if matches(r, q["want"])), None)
            kind = category(q["want"], index)
            by_kind.setdefault(kind, []).append(1 if rank and rank <= 5 else 0)
            hits1 += rank == 1
            hits5 += bool(rank and rank <= 5)
            rr += 1 / rank if rank else 0.0
            per_query.append({"method": method, "query": q["query"], "want": q["want"], "rank": rank,
                              "top3": [r.name for r in ranked[:3]]})
            if args.show and (not rank or rank > 5):
                print(f"  MISS [{method}] {q['query']!r} -> want {q['want']}; got {[r.name for r in ranked[:3]]}")
        n = len(gold)
        latencies.sort()
        results[method] = {
            "recall@1": round(hits1 / n, 3), "recall@5": round(hits5 / n, 3), "mrr@10": round(rr / n, 3),
            "recall@5_by_kind": {k: f"{sum(v)}/{len(v)}" for k, v in sorted(by_kind.items())},
            "median_ms": round(latencies[len(latencies) // 2] * 1000, 1),
        }

    print(f"\n{len(gold)} questions")
    print(f"{'method':10} {'recall@1':>9} {'recall@5':>9} {'MRR@10':>7} {'median ms':>10}  recall@5 by kind")
    for m, r in results.items():
        print(f"{m:10} {r['recall@1']:>9.3f} {r['recall@5']:>9.3f} {r['mrr@10']:>7.3f} {r['median_ms']:>10}  "
              + ", ".join(f"{k} {v}" for k, v in r["recall@5_by_kind"].items()))

    out = ROOT / "results" / f"api_recall_{args.set}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({"set": args.set, "engine": index.status.engine, "entries": len(index.records),
                               "questions": len(gold), "methods": results, "per_query": per_query}, indent=2),
                   encoding="utf-8")
    print(f"\nwrote {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
