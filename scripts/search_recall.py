"""Offline recall of the connector's hf_search_tools against search/gold.toml.

    uv run python scripts/search_recall.py [--editor]

--editor also scores the editor's own hf_search_tools for comparison.
Needs a running editor (for the catalog), not an agent.
"""
from __future__ import annotations

import asyncio
import os
import sys
import tomllib
from pathlib import Path

os.environ["HULLFORGE_TOOL_MODE"] = "gateway"
from hullforge_mcp.server import HullForgeServer  # noqa: E402

GOLD = Path(__file__).resolve().parent.parent / "search" / "gold.toml"


async def main() -> int:
    srv = HullForgeServer()
    await srv._handle_list_tools(None, None)
    idx = srv._index
    gold = tomllib.load(GOLD.open("rb"))["q"]
    hits = {1: 0, 3: 0, 8: 0}
    ed_hits = {1: 0, 3: 0, 8: 0}
    for g in gold:
        want = set(g["want"].split("|"))
        missing = want - set(idx.entries)
        if missing == want:
            print(f"GOLD ERROR {g['query']!r}: none of {sorted(want)} exist")
            continue
        got = [e.name for _, e in idx.search(g["query"], limit=8)]
        for k in hits:
            hits[k] += bool(want & set(got[:k]))
        if not want & set(got[:3]):
            print(f"{'miss@8' if not want & set(got) else 'low   '} {g['query']!r:45} want {sorted(want)[:2]} got {got[:3]}")
        if "--editor" in sys.argv:
            r = await srv._dispatch("hf_search_tools", {"query": g["query"], "limit": 8})
            names = [x["name"] for x in (r.structured_content or {}).get("results", [])]
            for k in ed_hits:
                ed_hits[k] += bool(want & set(names[:k]))
    n = len(gold)
    print("connector  " + "  ".join(f"recall@{k} {hits[k]}/{n}" for k in hits))
    if "--editor" in sys.argv:
        print("editor     " + "  ".join(f"recall@{k} {ed_hits[k]}/{n}" for k in ed_hits))
    if srv._client:
        await srv._client.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
