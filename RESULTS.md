# Results

## Run 20261111-171454: 20 core tasks, 3 repeats

Claude Code 2.1.322 headless, Sonnet, full tool list (3,041 HullForge tools), seeded eval fixture.
Cost is Claude Code's API-equivalent estimate; runs used a subscription login.

| Runs | Pass rate | Median turns | Median cost (USD) | Tool precision | Tool recall |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 60 | 98% (59/60) | 3 | 0.048 | 0.95 | 1.00 |

| Category | Runs | Passed | Median turns | Median cost (USD) | Tool precision |
| --- | ---: | ---: | ---: | ---: | ---: |
| Actors | 12 | 12 | 3.5 | 0.042 | 1.00 |
| Blueprints | 9 | 9 | 4 | 0.055 | 1.00 |
| Diagnosis | 6 | 5 | 10.5 | 0.394 | 0.63 |
| Discovery | 9 | 9 | 3 | 0.032 | 1.00 |
| Materials | 9 | 9 | 3 | 0.049 | 1.00 |
| Properties | 15 | 15 | 3 | 0.047 | 0.96 |

Total for the run: about $9.64 API-equivalent and 9.9 minutes of agent time.

**Reading it.** Direct operations (find, read, set, create, delete) are solved in about three turns with
the right tool almost every time. Diagnosis is where the agent works hardest: three times the turns and
eight times the cost, and the only failure. See [FINDINGS.md](FINDINGS.md) for why.

## Run 20261111-165156: full vs catalog mode, 5 tasks

| Mode | Pass rate | Median turns | Median cost (USD) | Tool precision |
| --- | ---: | ---: | ---: | ---: |
| Full tool list | 4 / 5 | 3 | 0.031 | 1.00 |
| Catalog mode | 0 / 5 | 12 | 0.250 | 0.00 |

Catalog mode does not work inside Claude Code; see finding 1.
