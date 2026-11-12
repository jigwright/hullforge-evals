"""hf-eval: check, run and report.

  hf-eval check                 validate the fixture and every task against the live editor's schemas
  hf-eval reset                 reset the fixture once and print what changed
  hf-eval run [options]         run tasks through Claude Code and grade them
  hf-eval report <results dir>  build report.md from a run's results
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import statistics
import sys
import tomllib
from dataclasses import asdict
from pathlib import Path

from .agent import run_agent, tool_selection
from .bridge import Bridge, SchemaMismatch
from .fixture import load_fixture, reset
from .grading import grade

REPO = Path(__file__).resolve().parent.parent
DEFAULT_CONNECTOR = REPO.parent / "hullforge-mcp"

# "preset" mode: catalog mode with these areas listed from startup, instead of
# switched on mid-session. Covers every tool the core tasks need.
DEFAULT_PRESET_AREAS = "Actors,Assets,Blueprints,Materials,Properties,Components,Lighting"


def load_task_file(path: Path) -> tuple[list[dict], list[dict]]:
    """A task file's tasks, and any [[seed]] steps it adds to the fixture."""
    with path.open("rb") as f:
        data = tomllib.load(f)
    return data["task"], data.get("seed", [])


def load_tasks(path: Path) -> list[dict]:
    return load_task_file(path)[0]


async def cmd_check(args: argparse.Namespace) -> int:
    problems = 0
    async with Bridge(args.project) as b:
        print(f"editor reports {len(b.schemas)} tools")
        tasks, seed = load_task_file(Path(args.tasks))
        for step in load_fixture()["step"] + seed:
            try:
                b.check(step["tool"], step.get("args", {}))
            except SchemaMismatch as e:
                problems += 1
                print(f"FIXTURE  {e}")
        for extra in [("hf_list_actors", {"label_contains": "Eval", "limit": 500}),
                      ("hf_delete_actor", {"actor": "x", "confirm": True}), ("hf_delete_asset", {"object": "/Game/x", "confirm": True}),
                      ("hf_find_assets", {"path": "/Game/EvalFixture", "limit": 500})]:
            try:
                b.check(*extra)
            except SchemaMismatch as e:
                problems += 1
                print(f"RESET    {e}")
        for task in tasks:
            names = [n for e in task.get("expected_tools", []) for n in e.split("|")]
            for t in names + task.get("acceptable_tools", []):
                if t not in b.schemas:
                    problems += 1
                    print(f"TASK     {task['id']}: {t} is not in the editor's tool list")
            for c in task["checks"]:
                if "tool" in c:
                    try:
                        b.check(c["tool"], c.get("args", {}))
                    except SchemaMismatch as e:
                        problems += 1
                        print(f"CHECK    {task['id']}: {e}")
    print("all good" if not problems else f"{problems} problem(s)")
    return 1 if problems else 0


async def cmd_reset(args: argparse.Namespace) -> int:
    seed = load_task_file(Path(args.tasks))[1] if args.tasks else []
    async with Bridge(args.project) as b:
        for line in await reset(b, extra_steps=seed):
            print(line)
    return 0


async def cmd_run(args: argparse.Namespace) -> int:
    tasks, seed = load_task_file(Path(args.tasks))
    if args.only:
        tasks = [t for t in tasks if t["id"] in args.only.split(",")]
    tasks = tasks[: args.limit] if args.limit else tasks
    modes = args.modes.split(",")
    out = Path(args.out) / dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    out.mkdir(parents=True, exist_ok=True)
    (out / "run.json").write_text(json.dumps(vars(args), indent=2, default=str))
    total = len(tasks) * len(modes) * args.repeats
    n = 0
    async with Bridge(args.project) as b:
        for rep in range(1, args.repeats + 1):
            for task in tasks:
                for mode in modes:
                    n += 1
                    print(f"[{n}/{total}] {task['id']} mode={mode} rep={rep}", flush=True)
                    await reset(b, extra_steps=seed)
                    agent = await asyncio.to_thread(
                        run_agent, task["prompt"], model=args.model, max_turns=args.max_turns,
                        connector_dir=Path(args.connector), catalog_mode=(mode in ("catalog", "preset")),
                        tool_mode="gateway" if mode == "gateway" else "full",
                        areas=args.areas.split(",") if mode == "preset" else None,
                        project_dir=args.project,
                    )
                    g = await grade(b, task["checks"], agent.answer, agent.tools_called)
                    precision, recall = tool_selection(
                        agent.tools_called, task.get("expected_tools", []), task.get("acceptable_tools", []))
                    stem = f"{task['id']}__{mode}__{rep}"
                    result = {
                        "task": task["id"], "category": task.get("category", ""), "mode": mode,
                        "repeat": rep, "model": args.model, "passed": g.passed and not agent.is_error,
                        "checks": [asdict(c) for c in g.checks],
                        "tool_precision": precision, "tool_recall": recall,
                        **{k: v for k, v in asdict(agent).items() if k != "raw_events"},
                    }
                    (out / f"{stem}.json").write_text(json.dumps(result, indent=2))
                    with (out / f"{stem}.events.jsonl").open("w", encoding="utf-8") as f:
                        for ev in agent.raw_events:
                            f.write(json.dumps(ev) + "\n")
                    status = "PASS" if result["passed"] else "FAIL"
                    print(f"    {status} turns={agent.num_turns} cost=${agent.cost_usd:.4f} "
                          f"tools={len(agent.tools_called)} p={precision} r={recall} {agent.subtype}", flush=True)
    print(f"results in {out}")
    write_report(out)
    return 0


def write_report(out: Path) -> Path:
    rows = [json.loads(p.read_text()) for p in sorted(out.glob("*.json")) if p.name != "run.json"]
    lines = [f"# HullForge eval report: {out.name}", ""]
    if not rows:
        lines.append("No results.")
    else:
        lines += ["## By mode", "",
                  "| Mode | Runs | Pass rate | Median turns | Median startup context | Median input tokens | Median cost (USD) | Tool precision | Tool recall |",
                  "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
        for mode in sorted({r["mode"] for r in rows}):
            rs = [r for r in rows if r["mode"] == mode]
            med = lambda xs: statistics.median(xs) if xs else 0
            tok = [r["usage"].get("input_tokens", 0) + r["usage"].get("cache_read_input_tokens", 0)
                   + r["usage"].get("cache_creation_input_tokens", 0) for r in rs]
            lines.append(
                f"| {mode} | {len(rs)} | {sum(r['passed'] for r in rs) / len(rs):.0%} | {med([r['num_turns'] for r in rs])} "
                f"| {med([r.get('startup_tokens', 0) for r in rs]):,.0f} | {med(tok):,.0f} | {med([r['cost_usd'] for r in rs]):.4f} "
                f"| {statistics.mean(r['tool_precision'] for r in rs):.2f} | {statistics.mean(r['tool_recall'] for r in rs):.2f} |")
        gws = [r for r in rows if r.get("gateway")]
        if gws:
            calls = sum(r["gateway"]["calls"] for r in gws)
            first = sum(r["gateway"]["calls_schema_first"] for r in gws)
            lines += ["", "## Gateway", "",
                      "| Runs | Searches per run | Schema fetches per run | Calls | Schema fetched first | Refused: schema | Refused: wrong caller |",
                      "| ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
                      f"| {len(gws)} | {statistics.mean(r['gateway']['searches'] for r in gws):.1f} "
                      f"| {statistics.mean(r['gateway']['schema_fetches'] for r in gws):.1f} | {calls} "
                      f"| {first / calls if calls else 0:.0%} | {sum(r['gateway']['schema_refusals'] for r in gws)} "
                      f"| {sum(r['gateway']['caller_refusals'] for r in gws)} |"]
        lines += ["", "## By task", "", "| Task | Mode | Rep | Result | Turns | Cost (USD) | Failed checks |",
                  "| --- | --- | ---: | --- | ---: | ---: | --- |"]
        for r in rows:
            failed = "; ".join(f"{'(soft) ' if c.get('soft') else ''}{c['name']}: {c['detail']}"
                               for c in r["checks"] if not c["passed"])
            if r.get("is_error"):
                failed = (failed + "; " if failed else "") + f"agent error: {r.get('subtype')}"
            lines.append(f"| {r['task']} | {r['mode']} | {r['repeat']} | {'PASS' if r['passed'] else 'FAIL'} "
                         f"| {r['num_turns']} | {r['cost_usd']:.4f} | {failed} |")
        lines += ["", "Cost is Claude Code's API-equivalent estimate; runs used a subscription login."]
    path = out / "report.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def main() -> None:
    p = argparse.ArgumentParser(prog="hf-eval")
    p.add_argument("--project", default=None, help="Unreal project dir, if several editors are open")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check"); c.add_argument("--tasks", default=str(REPO / "tasks" / "core.toml"))
    rs = sub.add_parser("reset"); rs.add_argument("--tasks", default="", help="also run this task file's [[seed]] steps")
    r = sub.add_parser("run")
    r.add_argument("--tasks", default=str(REPO / "tasks" / "core.toml"))
    r.add_argument("--modes", default="full", help="comma list of full, catalog, preset, gateway")
    r.add_argument("--areas", default=DEFAULT_PRESET_AREAS, help="areas listed at startup in preset mode")
    r.add_argument("--repeats", type=int, default=1)
    r.add_argument("--model", default="sonnet")
    r.add_argument("--max-turns", type=int, default=25)
    r.add_argument("--limit", type=int, default=0)
    r.add_argument("--only", default="")
    r.add_argument("--connector", default=str(DEFAULT_CONNECTOR))
    r.add_argument("--out", default=str(REPO / "results"))
    rep = sub.add_parser("report"); rep.add_argument("dir")
    args = p.parse_args()
    if args.cmd == "report":
        print(write_report(Path(args.dir)))
        sys.exit(0)
    fn = {"check": cmd_check, "reset": cmd_reset, "run": cmd_run}[args.cmd]
    sys.exit(asyncio.run(fn(args)))
