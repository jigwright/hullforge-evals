"""Oracle for the cross-area suite: solve each task directly, then grade it.

Every check must pass on a correct solution, or the check is wrong. Read-only
tasks get the answer a correct agent would give. Run against a live editor:

    uv run python scripts/cross_area_oracle.py [--dump]

--dump prints each state check's tool output, for writing new checks.
--null does nothing instead of solving, and expects every task to FAIL: a
check that passes on an untouched fixture is not measuring the task.
"""
from __future__ import annotations

import asyncio
import json
import sys
import tomllib
from pathlib import Path

from evals.bridge import Bridge
from evals.fixture import reset
from evals.grading import grade

TASKS = Path(__file__).resolve().parent.parent / "tasks" / "cross_area.toml"
SEQ, DATA, AUD = "/Game/EvalFixture/Seq", "/Game/EvalFixture/Data", "/Game/EvalFixture/Audio"


async def solve(b: Bridge, task_id: str) -> tuple[list[str], str]:
    """Do the task the way a correct agent would. Returns (tools, answer)."""
    calls: list[tuple[str, dict]] = []
    answer = "Done."

    async def c(tool: str, args: dict):
        calls.append((tool, args))
        return await b.call(tool, args)

    if task_id == "xa.create_sequence":
        await c("hf_create_level_sequence", {"destination": f"{SEQ}/LS_Intro", "duration_seconds": 10})
    elif task_id == "xa.bind_actor":
        await c("hf_add_sequence_binding", {"sequence": f"{SEQ}/LS_Shot", "actor": "EvalRock_A"})
    elif task_id == "xa.playback_range":
        await c("hf_set_sequence_playback_range", {"sequence": f"{SEQ}/LS_Shot", "start": 0, "end": 120, "units": "frames"})
    elif task_id == "xa.sequence_question":
        r = await c("hf_list_sequence_bindings", {"sequence": f"{SEQ}/LS_Shot"})
        answer = "It animates EvalSun." if "EvalSun" in json.dumps(r) else "None."
    elif task_id == "xa.transform_track":
        r = await c("hf_list_sequence_bindings", {"sequence": f"{SEQ}/LS_Shot"})
        guid = next(x.get("guid") or x.get("binding_guid") for x in r.get("bindings", []) if "EvalSun" in json.dumps(x))
        await c("hf_add_sequence_track", {"sequence": f"{SEQ}/LS_Shot", "kind": "Transform", "binding_guid": guid})
    elif task_id == "xa.create_enum":
        await c("hf_create_enum", {"destination": f"{DATA}/E_Rarity"})
        for n in ("Common", "Rare", "Epic"):
            await c("hf_add_enum_entry", {"enum": f"{DATA}/E_Rarity", "display_name": n})
    elif task_id == "xa.create_struct":
        await c("hf_create_struct", {"destination": f"{DATA}/S_Loot"})
        await c("hf_add_struct_member", {"struct": f"{DATA}/S_Loot", "member": "Weight", "type": "float"})
    elif task_id == "xa.curve":
        await c("hf_create_curve", {"destination": f"{DATA}/C_Falloff"})
        await c("hf_set_curve_key", {"curve": f"{DATA}/C_Falloff", "time": 0, "value": 1})
        await c("hf_set_curve_key", {"curve": f"{DATA}/C_Falloff", "time": 1, "value": 0})
    elif task_id == "xa.data_table":
        await c("hf_create_data_table", {"destination": f"{DATA}/DT_Items", "row_struct": f"{DATA}/S_Item"})
        await c("hf_add_data_table_row", {"data_table": f"{DATA}/DT_Items", "row": "Sword"})
    elif task_id == "xa.foliage_type":
        await c("hf_create_foliage_type", {"path": "/Game/EvalFixture/Foliage/FT_Cube", "mesh": "/Engine/BasicShapes/Cube"})
    elif task_id == "xa.attenuation":
        await c("hf_create_attenuation", {"destination": f"{AUD}/ATT_Eval", "falloff_distance": 2000})
    elif task_id == "xa.sound_cue":
        await c("hf_create_sound_cue", {"destination": f"{AUD}/CUE_Eval"})
    elif task_id == "xa.post_process":
        await c("hf_add_post_process_volume", {"label": "EvalPPV", "unbound": True})
    elif task_id == "xa.mesh_triangles":
        r = await c("hf_get_mesh_info", {"mesh": "/Engine/BasicShapes/Cube"})
        answer = f"LOD 0 has {r['triangles_lod0']} triangles."
    elif task_id == "xa.collision_question":
        r = await c("hf_describe_component_collision_settings", {"actor": "EvalRock_A"})
        answer = f"It uses the {r['collision_profile_name']} profile."
    elif task_id == "xa.chain_mi_sequence":
        await c("hf_create_material_instance", {"parent": "/Game/EvalFixture/Materials/M_Rock",
                                                "destination": "/Game/EvalFixture/Materials/MI_Pulse"})
        await c("hf_create_level_sequence", {"destination": f"{SEQ}/LS_Pulse"})
        await c("hf_add_sequence_binding", {"sequence": f"{SEQ}/LS_Pulse", "actor": "EvalRock_B"})
    elif task_id == "xa.chain_data":
        await c("hf_create_enum", {"destination": f"{DATA}/E_Slot"})
        for n in ("Head", "Chest"):
            await c("hf_add_enum_entry", {"enum": f"{DATA}/E_Slot", "display_name": n})
        await c("hf_create_struct", {"destination": f"{DATA}/S_Gear"})
        await c("hf_add_struct_member", {"struct": f"{DATA}/S_Gear", "member": "Armor", "type": "float"})
    else:
        raise KeyError(task_id)
    return [t for t, _ in calls], answer


async def main() -> int:
    data = tomllib.load(TASKS.open("rb"))
    bad = 0
    async with Bridge() as b:
        for task in data["task"]:
            await reset(b, extra_steps=data.get("seed", []))
            try:
                tools, answer = ([], "Done.") if "--null" in sys.argv else await solve(b, task["id"])
            except Exception as exc:  # noqa: BLE001
                print(f"{task['id']}: SOLVE FAILED {exc}")
                bad += 1
                continue
            g = await grade(b, task["checks"], answer, tools)
            if "--null" in sys.argv:
                print(f"{task['id']}: {'FAIL (good)' if not g.passed else 'PASSES WITH NOTHING DONE'}")
                bad += g.passed
                continue
            print(f"{task['id']}: {'PASS' if g.passed else 'FAIL'}")
            for ch, res in zip(task["checks"], g.checks):
                if not res.passed:
                    print(f"   - {res.name}: {res.detail}")
                if "--dump" in sys.argv and "tool" in ch and ("PLACEHOLDER" in json.dumps(ch) or not res.passed):
                    print("     STATE:", (await b.call_text(ch["tool"], ch.get("args", {})))[:1200])
                if "--dump" in sys.argv and "PLACEHOLDER" in json.dumps(ch) and "tool" not in ch:
                    print("     ANSWER:", answer[:1200])
            bad += not g.passed
        await reset(b)
    print("oracle OK" if not bad else f"{bad} task(s) need fixing")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
