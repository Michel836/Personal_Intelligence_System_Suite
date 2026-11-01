# Makefile for 36TB Intelligence
#
# Single source of truth for dependencies: pyproject.toml (+ constraints.txt).

PY ?= .venv/bin/python
PIP := $(PY) -m pip

.PHONY: help install install-dev setup test test-fast test-release acceptance \
        lint typecheck quality format format-check clean run scan ui lite smart full profile

help:
	@echo "36TB Intelligence - Personal Knowledge Operating System"
	@echo ""
	@echo "Available commands:"
	@echo "  install       Install core runtime (editable, constrained)"
	@echo "  install-dev   Install core + dev tools (editable, constrained)"
	@echo "  setup         Complete setup (install-dev + git hooks)"
	@echo "  test          Full test suite with coverage"
	@echo "  test-fast     Fast test suite (no coverage)"
	@echo "  test-release  Release acceptance suite"
	@echo "  acceptance    Fresh venv + wheel new-user acceptance"
	@echo "  lint          Ruff + mypy debt budget (scripts/quality_gate.py)"
	@echo "  typecheck     mypy only"
	@echo "  quality       lint + test (CI baseline)"
	@echo "  format        black + ruff format + isort"
	@echo "  clean         Remove caches and build artefacts"
	@echo "  scan          Scan a root (make scan ROOT=/path)"
	@echo "  ui            Start the canonical Streamlit UI"
	@echo "  lite|smart|full  Start a launch profile"

# ---------------------------------------------------------------------------
# Installation
# ---------------------------------------------------------------------------
install:
	$(PIP) install --upgrade pip setuptools wheel
	$(PIP) install -c constraints.txt -e .

install-dev:
	$(PIP) install --upgrade pip setuptools wheel
	$(PIP) install -c constraints.txt -e ".[dev]"

setup: install-dev
	$(PY) -c "from src.core.paths import ensure_layout; print(ensure_layout())"
	-$(PY) -m pre_commit install

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
test:
	$(PY) -m pytest -v --cov=src --cov-report=html --cov-report=term

test-fast:
	$(PY) -m pytest -q

test-release:
	$(PY) -m pytest tests/release tests/ui -q

acceptance:
	bash scripts/acceptance_new_user.sh

# ---------------------------------------------------------------------------
# Quality: a *budgeted* gate that must pass while the legacy debt is retired.
# ---------------------------------------------------------------------------
lint:
	$(PY) scripts/quality_gate.py

typecheck:
	$(PY) -m mypy src

quality: lint test

format:
	$(PY) -m black src/ scripts/ tests/
	$(PY) -m ruff format src/ scripts/ tests/
	$(PY) -m isort src/ scripts/ tests/

format-check:
	$(PY) -m black --check src/ scripts/ tests/
	$(PY) -m ruff format --check src/ scripts/ tests/

# ---------------------------------------------------------------------------
# Cleaning
# ---------------------------------------------------------------------------
clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	find . -type f -name ".coverage" -delete
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage
	rm -rf dist build
	rm -rf *.egg-info

# ---------------------------------------------------------------------------
# Running
# ---------------------------------------------------------------------------
run:
	$(PY) -m src.cli scan $(ROOT) --limit 1000

scan:
ifndef ROOT
	@echo "Usage: make scan ROOT=/path/to/corpus"
else
	$(PY) -m src.cli scan $(ROOT)
endif

ui:
	$(PY) -m src.launcher --profile full

lite:
	$(PY) -m src.launcher --profile lite

smart:
	$(PY) -m src.launcher --profile smart

full:
	$(PY) -m src.launcher --profile full

profile:
	$(PY) -m src.cli scan $(ROOT) --limit 1000
