.PHONY: format lint typecheck test precommit install-precommit check

VENV := .venv/bin
PYTHON ?= $(VENV)/python
PRE_COMMIT ?= $(PYTHON) -m pre_commit
PRE_COMMIT_CONFIG ?= .pre_commit_config.yaml

setup:
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -r requirements.txt

format:
	$(VENV)/black src
	$(VENV)/ruff check --fix src

lint:
	$(VENV)/ruff check src

typecheck:
	$(VENV)/mypy src --strict

test:
	$(VENV)/pytest --maxfail=1 --disable-warnings -q

precommit:
	$(PRE_COMMIT) run --all-files --show-diff-on-failure --config $(PRE_COMMIT_CONFIG)

install-precommit:
	$(PRE_COMMIT) install --config $(PRE_COMMIT_CONFIG)

check: precommit test
