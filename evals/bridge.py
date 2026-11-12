"""Direct bridge access for seeding the fixture and grading results.

The agent under test talks to the editor through hullforge-mcp. The harness
talks to the same editor directly, outside the agent's session, so grading
reads the editor's real state rather than anything the agent claimed.

Every call is checked against the schema the editor itself reports through
hf_describe_tools, so a stale argument name fails loudly here instead of
quietly producing a fixture or a grade that means nothing.
"""
from __future__ import annotations

import json
from typing import Any

from hullforge_mcp.client import BridgeClient
from hullforge_mcp.session import discover_all


class SchemaMismatch(Exception):
    """A harness call does not match the live tool schema."""


class Bridge:
    def __init__(self, project_dir: str | None = None) -> None:
        self._project_dir = project_dir
        self._client: BridgeClient | None = None
        self.schemas: dict[str, dict[str, Any]] = {}

    async def __aenter__(self) -> "Bridge":
        sessions = discover_all(self._project_dir)
        if not sessions:
            raise RuntimeError(
                "No running Unreal editor with HullForge was found. Open the eval "
                "project first."
            )
        self._client = BridgeClient(sessions[0])
        await self._client.connect()
        described = await self._client.call("hf_describe_tools")
        for entry in described.get("tools", []):
            if entry.get("name"):
                self.schemas[entry["name"]] = entry.get("input_schema") or {}
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._client is not None:
            await self._client.close()

    def check(self, tool: str, args: dict[str, Any]) -> None:
        if tool not in self.schemas:
            raise SchemaMismatch(f"{tool} is not in the editor's tool list")
        schema = self.schemas[tool]
        props = schema.get("properties", {}) or {}
        missing = [k for k in schema.get("required", []) or [] if k not in args]
        unknown = [k for k in args if props and k not in props]
        if missing or (unknown and schema.get("additionalProperties") is False):
            raise SchemaMismatch(
                f"{tool}: missing {missing}, unknown {unknown}; "
                f"accepts {sorted(props)}"
            )

    async def call(self, tool: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
        args = args or {}
        self.check(tool, args)
        assert self._client is not None
        return await self._client.call(tool, args)

    async def call_text(self, tool: str, args: dict[str, Any] | None = None) -> str:
        """The result as one JSON string, for contains/count style checks."""
        return json.dumps(await self.call(tool, args), sort_keys=True)
