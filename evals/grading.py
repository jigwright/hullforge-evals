"""Grade a run by reading the editor's state, not by trusting the agent.

A task lists checks. Each check either looks at the agent's final answer, or
calls a HullForge tool directly through the bridge and inspects what comes back.
A run passes only if every check passes.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .bridge import Bridge


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class Grade:
    passed: bool
    checks: list[CheckResult] = field(default_factory=list)


def _norm(s: str) -> str:
    return s.lower()


def _has_word(text: str, value: str) -> bool:
    """value appears as a whole token, so M_Rock does not match inside MI_Rock_Wet."""
    return re.search(r"(?<![A-Za-z0-9_])" + re.escape(value.lower()) + r"(?![A-Za-z0-9_])", text.lower()) is not None


async def run_check(bridge: Bridge, check: dict[str, Any], answer: str) -> CheckResult:
    kind = check["kind"]
    name = check.get("name", kind)

    if kind == "answer_includes":
        missing = [s for s in check["values"] if not _has_word(answer, s)]
        return CheckResult(name, not missing, f"missing from answer: {missing}" if missing else "")

    if kind == "answer_excludes":
        present = [s for s in check["values"] if _has_word(answer, s)]
        return CheckResult(name, not present, f"should not appear: {present}" if present else "")

    if kind == "answer_number":
        nums = [int(n) for n in re.findall(r"\b\d+\b", answer)]
        ok = check["equals"] in nums
        return CheckResult(name, ok, "" if ok else f"expected {check['equals']}, saw {nums[:10]}")

    if kind == "state_includes":
        text = await bridge.call_text(check["tool"], check.get("args", {}))
        missing = [s for s in check["values"] if s not in text]
        return CheckResult(name, not missing, f"not in editor state: {missing}" if missing else "")

    if kind == "state_excludes":
        text = await bridge.call_text(check["tool"], check.get("args", {}))
        present = [s for s in check["values"] if s in text]
        return CheckResult(name, not present, f"unexpectedly in editor state: {present}" if present else "")

    if kind == "state_count":
        text = await bridge.call_text(check["tool"], check.get("args", {}))
        count = len(set(re.findall(check["pattern"], text)))
        ok = count == check["equals"]
        return CheckResult(name, ok, "" if ok else f"expected {check['equals']}, found {count}")

    if kind == "state_regex":
        text = await bridge.call_text(check["tool"], check.get("args", {}))
        ok = re.search(check["pattern"], text) is not None
        return CheckResult(name, ok, "" if ok else f"pattern {check['pattern']!r} not found")

    raise ValueError(f"unknown check kind {kind!r}")


async def grade(bridge: Bridge, checks: list[dict[str, Any]], answer: str) -> Grade:
    results = []
    for check in checks:
        try:
            results.append(await run_check(bridge, check, answer))
        except Exception as exc:  # a grading error is a failed check, never a pass
            results.append(CheckResult(check.get("name", check["kind"]), False, f"grader error: {exc}"))
    return Grade(all(r.passed for r in results), results)
