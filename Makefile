.PHONY: build-sandbox test lint typecheck eval-compare

TASKS ?= data/tasks/seed_50.jsonl

build-sandbox:
	docker build -f Dockerfile.sandbox -t coding-eval-sandbox:latest .

test:
	uv run pytest

lint:
	uv run ruff check .

typecheck:
	uv run mypy src

# Head-to-head: single-shot vs agentic over $(TASKS) (override TASKS=...).
# Requires ANTHROPIC_API_KEY + the sandbox image (make build-sandbox).
eval-compare:
	uv run coding-eval run --agents claude-code --agents claude-code-agentic \
		--tasks-file $(TASKS) --output-dir results/agentic_compare
	uv run python scripts/compare_agents.py results/agentic_compare/leaderboard.json
