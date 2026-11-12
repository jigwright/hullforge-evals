# Findings

## 1. Catalog mode does not work in Claude Code, and isn't needed there (11 Nov 2026)

**Setup.** 5 smoke tasks, 1 run each per mode, Claude Code 2.1.322 headless on Sonnet, HullForge with
3,041 tools, against the seeded eval fixture. Run `20261111-165156`.

| Mode | Pass rate | Median turns | Median cost (API-equivalent) | Tool precision | Tool recall |
| --- | ---: | ---: | ---: | ---: | ---: |
| Full tool list | 4 / 5 | 3 | $0.031 | 1.00 | 1.00 |
| Catalog mode | 0 / 5 | 12 | $0.250 | 0.00 | 0.00 |

**What happened.** In every catalog run the agent did the right thing: it listed the tool areas and
enabled the right one (for example Actors, after which HullForge reported 121 tools listed). None of
those tools ever became callable. Claude Code defers large MCP tool lists behind its own `ToolSearch`
and does not re-index tools announced by `tools/list_changed` mid-session, so the agent searched for
tools that were enabled but never indexed, about six times per run, and then reported honestly that it
could not do the task.

**Why full mode is fine.** Claude Code's `ToolSearch` already does what catalog mode was built for: it
loads only the tools the task needs. With all 3,041 tools listed, the agent found the right tool on the
first search every time.

**Decision.** Catalog mode stays, documented as unsuitable for Claude Code and kept for clients that
load every tool up front. The harness now runs full mode by default.

**Also seen.** The first full-mode run, with a cold prompt cache, cost about $0.34 per task (about
262,000 input tokens, mostly the tool list). Once the cache was warm, the same tasks cost about $0.03.

## 2. The agent confuses materials with material instances

Asked for "every material instance under /Game/EvalFixture", the agent listed the parent materials
`M_Rock` and `M_Sand` along with the three real instances. The grader, which checks answers as whole
words, failed it. This is the kind of mistake the benchmark exists to catch, and a candidate for a
clearer tool result (class shown per row) or tool description.

## 3. The agent caught a flaw in the benchmark itself

The first version of `diagnosis.hidden_in_game` said EvalRock_B "shows up in the editor but disappears
in Play". The fixture's rocks had no mesh assigned, so they were invisible in the editor too. The agent
reported that, which was correct, and the grader passed it only because the word "hidden" appeared
somewhere in the answer. Two fixes followed: the rocks now get a real mesh, and the grader requires the
actual cause (`bHidden`, "hidden in game"). The lesson is the same one as the article's: a check that
passes for the wrong reason is worse than no check.

## 4. Agents find better routes than the task author

Asked which instances use M_Rock as their parent, the agent used `hf_list_material_children`, a more
direct tool than the two the task listed. Tasks now accept alternative tools (`"a|b"` in
`expected_tools`), so a better route isn't scored as a miss.

## 5. HullForge: `hf_get_property` can't read a path that `hf_set_property` can write

`hf_set_property` accepts `StaticMeshComponent.StaticMesh` on an actor and verifies the write;
`hf_get_property` with the same path answers "No property". A gap for the HullForge backlog.
