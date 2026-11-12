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

Tasks can run in two modes: **full** (every tool listed up front) and **catalog** (a small core, with tool
areas switched on as needed). The first comparison showed catalog mode does not work inside Claude Code,
which already defers large tool lists itself, so `run` uses full mode by default. See [FINDINGS.md](FINDINGS.md).

## How a run works

1. Reset the fixture: remove everything under `/Game/EvalFixture` and every actor labelled `Eval*`, then
   re-seed from `fixtures/eval_fixture.toml`. No editor restart.
2. Run the task with `claude -p`, given only the HullForge MCP server and none of Claude Code's built-in tools.
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

## License

MIT
