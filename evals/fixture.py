"""Reset the eval fixture: remove what the last run left, then re-seed.

Reset happens inside the open editor, so a run needs no editor restart and no
copying of project folders. Removal is scoped to /Game/EvalFixture and to actors
whose label starts with the fixture prefix; nothing else in the project is
touched.
"""
from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path
from typing import Any

from hullforge_mcp.client import ToolFailed

from .bridge import Bridge

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "eval_fixture.toml"


def load_fixture(path: Path = FIXTURE) -> dict[str, Any]:
    with path.open("rb") as f:
        return tomllib.load(f)


def _paths_in(text: str, root: str) -> list[str]:
    """Asset object paths under root, found anywhere in a tool result."""
    found = re.findall(re.escape(root) + r"/[A-Za-z0-9_/]+", text)
    return sorted(set(found))  # package paths only, so each asset appears once


def _labels_in(result: dict[str, Any], prefix: str) -> list[str]:
    text = json.dumps(result)
    return sorted(set(re.findall(r'"(' + re.escape(prefix) + r'[A-Za-z0-9_]*)"', text)))


async def reset(bridge: Bridge, fixture: dict[str, Any] | None = None) -> list[str]:
    """Clear and re-seed. Returns a log of what was done."""
    fixture = fixture or load_fixture()
    root, prefix = fixture["root"], fixture["actor_label_prefix"]
    log: list[str] = []

    actors = await bridge.call("hf_list_actors", {"label_contains": prefix, "limit": 500})
    for label in _labels_in(actors, prefix):
        await bridge.call("hf_delete_actor", {"actor": label, "confirm": True})
        log.append(f"deleted actor {label}")

    # Instances before parents, so a delete is never refused for being referenced.
    assets = await bridge.call_text("hf_find_assets", {"path": root, "limit": 500})
    paths = _paths_in(assets, root)
    paths.sort(key=lambda p: (0 if "/MI_" in p else 1, p))
    for p in paths:
        pkg = p.split(".")[0]
        try:
            await bridge.call("hf_delete_asset", {"object": pkg, "confirm": True})
        except ToolFailed:
            # A parent whose instances were deleted a moment ago can still look
            # referenced until the engine collects them. Everything under root
            # belongs to the fixture, so breaking those references is safe here
            # and nowhere else.
            try:
                await bridge.call("hf_delete_asset", {"object": pkg, "confirm": True, "delete_referenced": True})
            except ToolFailed as exc:
                if "No package" not in str(exc):
                    raise
                # The registry still lists it, but the package is already gone.
                log.append(f"already gone {p}")
                continue
        log.append(f"deleted asset {p}")

    for step in fixture["step"]:
        await bridge.call(step["tool"], step.get("args", {}))
        log.append(f"seeded {step['tool']} {step.get('args', {})}")
    return log
