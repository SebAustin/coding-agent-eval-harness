.PHONY: build-sandbox test lint typecheck

build-sandbox:
	docker build -f Dockerfile.sandbox -t coding-eval-sandbox:latest .

test:
	uv run pytest

lint:
	uv run ruff check .

typecheck:
	uv run mypy src
