# Makefile for 36TB Intelligence

.PHONY: help install install-dev setup test lint format clean run scan ui

# Default target
help:
	@echo "36TB Intelligence - Personal Knowledge Operating System"
	@echo ""
	@echo "Available commands:"
	@echo "  install     Install production dependencies"
	@echo "  install-dev Install development dependencies"
	@echo "  setup       Complete setup (install + configure)"
	@echo "  test        Run test suite"
	@echo "  lint        Run code linting"
	@echo "  format      Format code"
	@echo "  clean       Clean temporary files"
	@echo "  run         Run quick scan test"
	@echo "  scan        Scan specific drive (make scan DRIVE=C:)"
	@echo "  ui          Start Streamlit UI"

# Installation
install:
	pip install --upgrade pip setuptools wheel
	pip install -r requirements.txt

install-dev: install
	pip install -r requirements-dev.txt
	pre-commit install

# Setup
setup: install-dev
	@echo "Creating data directories..."
	mkdir -p data/{cache,indexes,reports,logs}
	@echo "Setup complete! Copy .env.example to .env and configure."

# Testing
test:
	pytest -v --cov=src --cov-report=html --cov-report=term

test-quick:
	pytest -v -x

# Code quality
lint:
	ruff check src/ scripts/ tests/
	mypy src/

format:
	black src/ scripts/ tests/
	ruff format src/ scripts/ tests/
	isort src/ scripts/ tests/

format-check:
	black --check src/ scripts/ tests/
	ruff format --check src/ scripts/ tests/

# Cleaning
clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	find . -type f -name "*.coverage" -delete
	rm -rf .pytest_cache/
	rm -rf .mypy_cache/
	rm -rf .ruff_cache/
	rm -rf htmlcov/
	rm -rf dist/
	rm -rf build/
	rm -rf *.egg-info/

# Running
run:
	python scripts/quick_scan.py C: 1000

scan:
ifndef DRIVE
	@echo "Usage: make scan DRIVE=C:"
else
	python scripts/quick_scan.py $(DRIVE) 5000
endif

ui:
	streamlit run src/ui/app.py

# Development utilities
check-install:
	python scripts/verify_installation.py

profile:
	py-spy record -o profile.svg -- python scripts/quick_scan.py C: 1000

# Database operations
db-init:
	alembic upgrade head

db-migrate:
	alembic revision --autogenerate -m "Auto migration"

db-upgrade:
	alembic upgrade head

db-downgrade:
	alembic downgrade -1

# Docker operations
docker-build:
	docker-compose build

docker-up:
	docker-compose up -d

docker-down:
	docker-compose down

docker-logs:
	docker-compose logs -f

# Documentation
docs:
	mkdocs serve

docs-build:
	mkdocs build

# CI/CD
ci: format-check lint test
	@echo "All CI checks passed!"