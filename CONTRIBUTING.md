# Contributing to Phantomime

Thank you for your interest in contributing. This document covers how to set up a development environment, run the test suite, and submit changes.

---

## Table of Contents

- [Development Setup](#development-setup)
- [Project Structure](#project-structure)
- [Running Tests](#running-tests)
- [Code Style](#code-style)
- [Submitting Changes](#submitting-changes)
- [Reporting Bugs](#reporting-bugs)
- [Feature Requests](#feature-requests)

---

## Development Setup

### Requirements

- Python 3.10+
- Git

### Steps

```bash
# Fork and clone the repo
git clone https://github.com/Tanwydd/phantomime.git
cd phantomime

# Create a virtual environment
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# Install in editable mode with dev dependencies
pip install -e ".[dev]"

# Install Playwright browsers
playwright install chromium

# Optional: install curl-cffi for TLS layer tests
pip install curl-cffi
```

### Dev dependencies

The `[dev]` extra installs:

- `pytest` + `pytest-asyncio` — test runner
- `ruff` — linter and formatter
- `mypy` — type checking
- `build` + `twine` — packaging

---

## Project Structure

```
phantomime/
├── phantomime/
│   ├── __init__.py       # Public API exports + __version__
│   └── browser.py        # HumanBrowser, run_swarm, run_swarm_multiprocess
├── tests/
│   ├── test_basic.py     # Import, instantiation, version checks
│   ├── test_fingerprint.py  # Fingerprint stability and coherence
│   ├── test_behavior.py  # Mouse, keyboard, scroll
│   └── test_swarm.py     # Concurrency tests
├── docs/
│   ├── ANTI_DETECTION.md
│   ├── PERFORMANCE_TUNING.md
│   ├── FAQ.md
│   ├── RECIPES.md
│   └── ARCHITECTURE.md
├── CHANGELOG.md
├── CONTRIBUTING.md
├── SECURITY.md
├── LICENSE
├── README.md
└── pyproject.toml
```

---

## Running Tests

```bash
# Full suite
pytest

# Skip tests that open a real browser (CI-friendly)
pytest -m "not browser"

# Single file
pytest tests/test_basic.py -v

# With coverage
pytest --cov=phantomime --cov-report=term-missing
```

Tests that launch a real Chromium instance are marked with `@pytest.mark.browser`. They are excluded from CI by default to keep runs fast, but should be run locally before opening a PR that touches `browser.py`.

---

## Code Style

Phantomime uses `ruff` for both linting and formatting.

```bash
# Check
ruff check phantomime/

# Format
ruff format phantomime/

# Type check
mypy phantomime/
```

All three must pass cleanly before a PR is merged. The CI pipeline runs them automatically.

### Key conventions

- All public methods are `async`.
- Type hints are mandatory on all public methods and function signatures.
- Internal helpers are prefixed with `_`.
- No external dependencies beyond `playwright`, `numpy`, and optionally `curl-cffi`. Keep the dependency surface minimal.
- Fingerprint patches are injected via `page.add_init_script()`. Never add patches anywhere else — they must be guaranteed to run before any page code.
- If you add a new detection vector patch, add the corresponding entry to the **Detection Vectors Covered** table in `PHANTOMIME.md`.

---

## Submitting Changes

1. Create a branch from `main`:
   ```bash
   git checkout -b fix/description-of-fix
   # or
   git checkout -b feat/description-of-feature
   ```

2. Make your changes. Keep commits focused — one logical change per commit.

3. Update `CHANGELOG.md` under `[Unreleased]`.

4. Run the full check suite:
   ```bash
   ruff check phantomime/ && ruff format phantomime/ && mypy phantomime/ && pytest
   ```

5. Open a Pull Request against `main`. Describe what changed and why. Link any related issue.

### PR checklist

- [ ] Tests added or updated
- [ ] `CHANGELOG.md` updated
- [ ] `ruff` and `mypy` pass
- [ ] No new external dependencies introduced without prior discussion

---

## Reporting Bugs

Open a [GitHub Issue](https://github.com/Tanwydd/phantomime/issues) with:

- Phantomime version (`pip show phantomime`)
- Python version
- OS and architecture
- Minimal reproducible example
- Full traceback if applicable
- Detection tool output (bot.sannysoft.com, creepjs) if the bug is fingerprint-related

---

## Feature Requests

Open an Issue with the `enhancement` label. Describe the use case first, then the proposed API. PRs without a prior issue discussion may be closed if they conflict with the project's design goals.
