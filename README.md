# hullforge-evals

An evaluation harness for [HullForge](https://github.com/jigwright/hullforge-mcp), the MCP server that lets
AI agents drive a live Unreal Engine 5 editor.

It runs real tasks through Claude Code against a real editor, then **grades the result by reading the
editor's state**, not by trusting what the agent says it did. The same rule HullForge applies to every
write, applied to evaluation.

## What it measures

| Metric | Why |
| --- | --- |
| Task success rate | The headline number |
| Tool-selection precision and recall | Did the agent use the right tools, and only those |
| Turns and wall-clock time | Efficiency |
| Input/output tokens and cost | What catalog mode is meant to save |
| Tool errors | How often the agent's calls were refused or failed |

Tasks can run in three modes:

- **full**: every tool listed up front. The default.
- **catalog**: a small core, with tool areas switched on mid-session as needed. This does not work inside
  Claude Code, which never re-reads the tool list ([finding 1](FINDINGS.md)).
- **preset**: catalog mode with the areas a suite needs listed from startup (`--areas`), the form of
  catalog mode Claude Code can use.
- **gateway**: five fixed tools (search, schema, read, write, destroy) in front of the whole catalog. The
  best result on every suite so far ([finding 9](FINDINGS.md)). Calls through the gateway are scored as the
  tool they carried, so precision, recall and the safety checks mean the same in every mode.

## Suites

| File | Tasks | What it tests |
| --- | ---: | --- |
| `tasks/core.toml` | 20 | Discovery, properties, materials, actors, Blueprints and diagnosis of planted faults |
| `tasks/injection.toml` | 7 | Prompt injection: hostile instructions planted in labels, tags, metadata, a graph comment, the log and a folder name |
| `tasks/cross_area.toml` | 17 | Tasks outside the `@general` preset's areas (Sequencer, Data, Foliage, Audio and more), and chains across areas |

A task file can add its own `[[seed]]` steps to the fixture; the injection suite plants its text that way.
`scripts/injection_control.py` is its negative control: it carries out every planted instruction itself
and confirms each task then grades FAIL, so a clean sweep can't come from checks that never fail.
`scripts/cross_area_oracle.py` does the same for the cross-area suite in both directions: solved, every
task passes; untouched (`--null`), every task fails. `scripts/search_recall.py` scores the gateway's
search offline against `search/gold.toml`.

Results: [RESULTS.md](RESULTS.md). What they taught us: [FINDINGS.md](FINDINGS.md).

## How a run works

1. Reset the fixture: remove everything under `/Game/EvalFixture` and every actor labelled `Eval*`, then
   re-seed from `fixtures/eval_fixture.toml`. No editor restart.
2. Run the task with `claude -p`, given only the HullForge MCP server and none of Claude Code's built-in tools,
   from an empty working directory so the agent can't see this repo (or the answers in it).
3. Grade by calling HullForge tools directly over the bridge, outside the agent's session.
4. Write one JSON result and the full event stream per run, then `report.md`.

Every seed and grading call is checked against the schema the editor reports through `hf_describe_tools`,
so a renamed argument fails loudly instead of producing a meaningless grade.

## Usage

Requires Windows, Unreal Engine 5.5 to 5.8 with the HullForge plugin, Python 3.13+, [uv](https://docs.astral.sh/uv/),
Claude Code (logged in), and `hullforge-mcp` checked out next to this repo.

```powershell
uv sync
# Open an Unreal project with HullForge enabled, then:
uv run hf-eval check                                   # validate fixture and tasks against the live editor
uv run hf-eval reset                                   # build the fixture once
uv run hf-eval run --limit 5 --modes full              # smoke run
uv run hf-eval run --repeats 3                         # full experiment
uv run hf-eval run --tasks tasks/injection.toml --repeats 3 --model haiku
uv run hf-eval run --modes preset --repeats 2           # catalog mode, areas listed at startup
uv run hf-eval run --modes full,preset,gateway --tasks tasks/cross_area.toml
uv run python scripts/injection_control.py             # negative control for the injection suite
uv run python scripts/compare.py results/<a> results/<b>  # modes side by side, cold and warm
uv run hf-eval report results/<run>                    # rebuild the report
```

Runs use Claude Code on a subscription login, not an API key, so they count against your usage limits. Cost
figures are Claude Code's API-equivalent estimate.

## Adding tasks

Tasks live in `tasks/*.toml`. Each has a prompt, the tools a correct solution needs (`expected_tools`),
other reasonable tools (`acceptable_tools`), and checks:

| Check | Passes when |
| --- | --- |
| `answer_includes` / `answer_excludes` | The final answer contains / does not contain the values |
| `answer_number` | The final answer contains the number |
| `state_includes` / `state_excludes` | A direct tool call's result contains / does not contain the values |
| `state_count` | A direct tool call's result has exactly N distinct regex matches |
| `state_regex` | A direct tool call's result matches the pattern |
| `answer_includes_any` | The final answer contains at least one of the values |
| `read_only` | The agent called no tool that writes |
| `tools_not_called` | The agent called none of the listed tools |

Add `soft = true` to a check to report it without letting it decide pass or fail.

## License

MIT
