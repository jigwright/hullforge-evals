"""Run one task through Claude Code in headless mode.

Claude Code runs on the user's subscription login, so no API key is needed.
It gets exactly one MCP server, HullForge, and none of its own built-in tools,
so the agent can only act on the editor through HullForge. Every event is
streamed as JSON and kept, so a run can be audited after the fact.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SERVER = "hullforge"
TOOL_PREFIX = f"mcp__{SERVER}__"

# Claude Code's own tools are switched off so the agent can only work through HullForge.
BUILTIN_TOOLS = [
    "Bash", "BashOutput", "KillShell", "Read", "Write", "Edit", "MultiEdit", "NotebookEdit",
    "Glob", "Grep", "LS", "WebFetch", "WebSearch", "Task", "TodoWrite", "ExitPlanMode",
]

# Tools that find or manage other tools rather than do the task: HullForge's catalog
# controls, and Claude Code's own ToolSearch, which it uses to load deferred MCP tools
# on a large tool list. They are counted separately and excluded from tool-selection scoring.
CATALOG_TOOLS = {"hf_list_tool_areas", "hf_enable_tool_areas", "hf_disable_tool_areas", "ToolSearch"}


@dataclass
class AgentRun:
    answer: str = ""
    tools_called: list[str] = field(default_factory=list)
    tool_errors: int = 0
    num_turns: int = 0
    duration_ms: int = 0
    cost_usd: float = 0.0
    usage: dict[str, int] = field(default_factory=dict)
    is_error: bool = False
    subtype: str = ""
    raw_events: list[dict[str, Any]] = field(default_factory=list)
    wall_s: float = 0.0


def find_claude() -> str:
    """The user's own Claude Code install, signed in with their subscription.

    The native installer puts claude.exe in ~/.local/bin. That is preferred over
    whatever is first on PATH, because a copy installed by another app can sit in
    that app's private sandbox, without the user's login.
    """
    override = os.environ.get("HF_EVAL_CLAUDE")
    if override:
        return override
    native = Path.home() / ".local" / "bin" / ("claude.exe" if os.name == "nt" else "claude")
    if native.exists():
        return str(native)
    return shutil.which("claude") or "claude"


def mcp_config(connector_dir: Path, catalog_mode: bool, project_dir: str | None,
               areas: list[str] | None = None) -> dict[str, Any]:
    """areas, with catalog_mode, lists those areas from startup. Claude Code
    reads the tool list once, so this is the form of catalog mode it can use."""
    env = {"HULLFORGE_CATALOG_MODE": "1" if catalog_mode else "0"}
    if catalog_mode and areas is not None:
        env["HULLFORGE_CATALOG_AREAS"] = ",".join(areas)
    if project_dir:
        env["HULLFORGE_PROJECT_DIR"] = project_dir
    return {
        "mcpServers": {
            SERVER: {
                "command": "uv",
                "args": ["run", "--directory", str(connector_dir), "hullforge-mcp"],
                "env": env,
            }
        }
    }


def agent_workdir() -> Path:
    """An empty directory, outside any git repo, for the agent to run in.

    Claude Code puts the working directory's git status and CLAUDE.md into the
    agent's context. Run from this repo and the agent can see the task files,
    including the names of the planted injections. A fixed path also keeps the
    system prompt identical from run to run, so prompt caching works.
    """
    base = Path(os.environ.get("LOCALAPPDATA") or tempfile.gettempdir())
    d = base / "hullforge-evals" / "agent-cwd"
    d.mkdir(parents=True, exist_ok=True)
    return d


def run_agent(
    prompt: str,
    *,
    model: str,
    max_turns: int,
    connector_dir: Path,
    catalog_mode: bool,
    areas: list[str] | None = None,
    project_dir: str | None = None,
    timeout_s: int = 900,
) -> AgentRun:
    claude = find_claude()
    cfg = mcp_config(connector_dir, catalog_mode, project_dir, areas)
    with tempfile.NamedTemporaryFile("w", suffix=".json", prefix=".mcp-run-", delete=False) as f:
        json.dump(cfg, f)
        cfg_path = f.name

    cmd = [
        claude, "-p", prompt,
        "--model", model,
        "--max-turns", str(max_turns),
        "--output-format", "stream-json", "--verbose",
        "--mcp-config", cfg_path, "--strict-mcp-config",
        "--allowedTools", f"mcp__{SERVER}",
        "--disallowedTools", ",".join(BUILTIN_TOOLS),
    ]

    run = AgentRun()
    start = time.monotonic()
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8",
            timeout=timeout_s, env={**os.environ}, cwd=agent_workdir(),
        )
        stdout = proc.stdout
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        run.is_error, run.subtype = True, "timeout"
    finally:
        run.wall_s = round(time.monotonic() - start, 2)
        Path(cfg_path).unlink(missing_ok=True)

    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        run.raw_events.append(ev)
        etype = ev.get("type")
        if etype == "assistant":
            for block in (ev.get("message", {}) or {}).get("content", []) or []:
                if block.get("type") == "tool_use":
                    name = block.get("name", "")
                    run.tools_called.append(name[len(TOOL_PREFIX):] if name.startswith(TOOL_PREFIX) else name)
        elif etype == "user":
            for block in (ev.get("message", {}) or {}).get("content", []) or []:
                if isinstance(block, dict) and block.get("type") == "tool_result" and block.get("is_error"):
                    run.tool_errors += 1
        elif etype == "result":
            run.answer = ev.get("result", "") or ""
            run.num_turns = int(ev.get("num_turns", 0) or 0)
            run.duration_ms = int(ev.get("duration_ms", 0) or 0)
            run.cost_usd = float(ev.get("total_cost_usd", ev.get("cost_usd", 0.0)) or 0.0)
            run.usage = {k: int(v) for k, v in (ev.get("usage") or {}).items() if isinstance(v, (int, float))}
            run.is_error = run.is_error or bool(ev.get("is_error"))
            run.subtype = run.subtype or str(ev.get("subtype", ""))
    if not run.subtype and not any(e.get("type") == "result" for e in run.raw_events):
        run.is_error, run.subtype = True, "no_result_event"
    return run


def tool_selection(
    called: list[str], expected: list[str], acceptable: list[str] | None = None
) -> tuple[float, float]:
    """Precision and recall of the distinct task tools the agent used.

    expected: tools a correct solution needs (recall is measured against these);
    an entry "a|b" accepts either tool.
    acceptable: other tools that are a reasonable part of a correct solution,
    such as a lookup before a write. They do not count against precision.
    """
    used = {t for t in called if t not in CATALOG_TOOLS}
    # Each expected entry may list alternatives as "a|b": either one satisfies it.
    groups = [set(e.split("|")) for e in expected]
    if not groups:
        return (1.0, 1.0)
    ok = set().union(*groups) | set(acceptable or [])
    precision = len(used & ok) / len(used) if used else 0.0
    recall = sum(1 for g in groups if used & g) / len(groups)
    return (round(precision, 3), round(recall, 3))
