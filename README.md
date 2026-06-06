# coding-agent-eval-harness

> Reproducible, contamination-aware eval harness for coding agents. 50 real PR-issue pairs, Docker-isolated execution, 5-axis rubric scoring, cross-agent leaderboard. Built so the benchmark can embarrass you.

[![CI](https://github.com/SebAustin/coding-agent-eval-harness/actions/workflows/ci.yml/badge.svg)](https://github.com/SebAustin/coding-agent-eval-harness/actions/workflows/ci.yml)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue)](https://www.python.org)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-green)](LICENSE)

## The problem with coding agent benchmarks in 2026

Every coding agent vendor quotes SWE-bench. The problems are well-documented:
models train on the test set (contamination), the benchmark only scores pass/fail
(a 3,000-line patch that passes tests scores the same as a 10-line one), and there
is no reproducible path from "run this on my tasks" to "this is what each agent
actually produced."

This repo is the answer: a harness you can run on a curated set of real GitHub
PR-issue pairs, with contamination detection, a 5-axis rubric that rewards minimal
correct diffs, and a leaderboard you can commit next to your code.

## Architecture

```mermaid
flowchart TD
    D[data/tasks/seed_50.jsonl\n50 PR-issue pairs] --> C[contamination.py\ncosine sim vs SWE-bench train]
    C --> R[Runner: task loop]
    R --> A1[ClaudeCode\nAdapter]
    R --> A2[Cursor\nAdapter]
    R --> A3[Aider\nAdapter]
    R --> A4[OpenAI Codex\nAdapter]
    A1 & A2 & A3 & A4 --> P[patch string]
    P --> S[DockerSandbox\ngit apply + pytest\n--network none --memory 512m]
    S --> RB[5-axis Rubric\ntest_pass · diff_minimality\ncomplexity · style · semantic]
    RB --> L[Leaderboard\nresults/leaderboard.md\nresults/leaderboard.json]
```

## Quickstart

```bash
git clone https://github.com/SebAustin/coding-agent-eval-harness && cd coding-agent-eval-harness
uv sync && cp .env.example .env
make build-sandbox     # build the Docker sandbox image (~2 min)
uv run coding-eval run --agents claude-code --limit 5 --smoke
```

## The 5-axis rubric

| Axis | Weight | Measures |
|---|---|---|
| `test_pass_rate` | 35% | Fraction of existing tests passing after patch |
| `diff_minimality` | 15% | 1 − (changed_lines / 200). Rewards surgical fixes. |
| `complexity_delta` | 15% | Cyclomatic complexity before vs after (radon). Lower = better. |
| `style_score` | 15% | ruff violations introduced in changed lines |
| `semantic_score` | 20% | Claude Sonnet 4.5 judge: does the patch correctly address the issue? |

## Leaderboard (v0.1.0, seed_50, contamination-free subset, n=42)

| Agent | Composite | Test pass | Diff min | Complexity | Style | Semantic | Cost/task |
|---|---|---|---|---|---|---|---|
| Claude Code (Sonnet 4.5) | **0.74** | 0.81 | 0.72 | 0.68 | 0.89 | 0.71 | $0.019 |
| Aider (GPT-4o) | 0.68 | 0.75 | 0.65 | 0.64 | 0.82 | 0.66 | $0.031 |
| OpenAI Codex | 0.61 | 0.69 | 0.58 | 0.61 | 0.78 | 0.59 | $0.028 |

*Contamination rate: 8/50 tasks (16%) flagged vs SWE-bench train. Clean-subset n=42.*

## Documentation

- [Methodology](docs/methodology.md) — task selection, contamination, judge model
- [Rubric design](docs/rubric_design.md) — per-axis formulas and weights
- [Contamination analysis](docs/contamination_analysis.md) — threshold and overlap stats
- [Adding agents](docs/adding_agents.md) — register a new `AgentAdapter`

## Sources

1. Jimenez et al. "SWE-bench: Can Language Models Resolve Real-World GitHub Issues?" ICLR 2024.
2. Cursor. "CursorBench: Measuring Agent Coding Performance with Blame-Traced Ground Truth." 2026.
3. Yang et al. "SWE-agent: Agent-Computer Interfaces Enable Automated Software Engineering." 2024.
4. Anthropic. Claude Code documentation, 2026.
5. Wortsman et al. "Model soups: averaging weights of multiple fine-tuned models improves accuracy." ICML 2022.