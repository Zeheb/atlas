# Development Guide

## Prerequisites

- Python 3.14+
- [`uv`](https://github.com/astral-sh/uv) (package and environment manager)
- Git

---

## Setup

```bash
# Clone the repository
git clone <repo-url>
cd Atlas

# Create and activate a virtual environment
uv venv
source .venv/bin/activate       # macOS / Linux
.venv\Scripts\activate          # Windows

# Install the project in editable mode with dev dependencies
uv pip install -e ".[dev]"
```

---

## Running Tests

```bash
# All tests
pytest

# Unit tests only (fast, no I/O)
pytest tests/unit/

# Integration tests
pytest tests/integration/

# With coverage
pytest --cov=atlas --cov-report=term-missing
```

---

## Code Style

This project uses:

| Tool | Purpose |
|---|---|
| `ruff` | Linting and formatting |
| `mypy` | Static type checking |
| `pytest` | Test runner |

```bash
# Lint and format
ruff check .
ruff format .

# Type check
mypy src/
```

All of the above must pass cleanly before merging.

---

## Configuration

Environment-specific configuration lives in `configs/`:

- `default.yaml` — baseline values for all environments
- `development.yaml` — overrides for local development
- `production.yaml` — overrides for production runs

The config loader merges these in order: `default` → environment-specific.
The active environment is set via the `ATLAS_ENV` environment variable (default: `development`).

---

## Branching Strategy

- `main` — stable, always releasable
- `dev` — integration branch for in-progress work
- Feature branches: `feature/<short-description>`
- Fix branches: `fix/<short-description>`

Pull requests target `dev`. `dev` is merged to `main` at stable milestones.

---

## Project Layout Reference

See [docs/architecture.md](architecture.md) for a full description of every package.
