.PHONY: format lint typecheck test precommit install-precommit check

VENV := .venv/bin
PYTHON ?= $(VENV)/python
PIP ?= .venv/bin/pip
PRE_COMMIT ?= $(PYTHON) -m pre_commit
PRE_COMMIT_CONFIG ?= .pre_commit_config.yaml

setup:
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -r requirements.txt

check-format:
	$(VENV)/black --check src
	$(VENV)/ruff check src

format:
	$(VENV)/black src
	$(VENV)/ruff check --fix src

lint:
	$(VENV)/ruff check src

typecheck:
	$(VENV)/mypy src --strict

test:
	$(VENV)/pytest --maxfail=1 --disable-warnings -q

install-dev:
	rm -rf .venv
	python3 -m venv .venv
	$(PIP) install -U pip
	if [ -f requirements.txt ]; then $(PIP) install -r requirements.txt; fi
	$(PIP) install black ruff mypy pytest pre-commit
	$(PIP) install pydantic pydantic-settings typer
	$(PIP) install types-requests types-PyYAML
	$(PIP) install universal-pathlib
	$(PIP) install requests types-requests


precommit:
	$(PRE_COMMIT) run --all-files --show-diff-on-failure --config $(PRE_COMMIT_CONFIG)

install-precommit:
	$(PRE_COMMIT) install --config $(PRE_COMMIT_CONFIG)

check: precommit test
