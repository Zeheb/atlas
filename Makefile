.PHONY: fmt lint type-check test check

fmt:
	uv run black .
	uv run ruff check --fix .

lint:
	uv run ruff check .
	uv run black --check .

type-check:
	uv run mypy src/

test:
	uv run pytest

check: lint type-check test
