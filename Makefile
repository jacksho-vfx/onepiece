.PHONY: setup format lint typecheck test precommit install-precommit check fixtures-pipelines tester-present install-dev check-format smoke-onepiece

VENV := .venv\Scripts
PYTHON ?= $(VENV)\python.exe
PIP ?= $(VENV)\pip.exe
PRE_COMMIT ?= $(PYTHON) -m pre_commit
PRE_COMMIT_CONFIG ?= .pre-commit-config.yaml
TESTER_ARGS ?=

$(PYTHON):
	python -m venv .venv

setup: $(PYTHON)
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -r requirements.txt

check-format:
	$(VENV)\black --check src

format:
	$(VENV)\black src

lint:
	$(VENV)\ruff check src

typecheck:
	$(VENV)\mypy

test:
	$(VENV)\pytest --maxfail=1 --disable-warnings -q

install-dev:
	if exist .venv rmdir /s /q .venv
	python -m venv .venv
	$(PIP) install -U pip
	$(PIP) install -e .[dev]

precommit:
	$(PRE_COMMIT) run --all-files --show-diff-on-failure --config $(PRE_COMMIT_CONFIG)

install-precommit:
	$(PRE_COMMIT) install --config $(PRE_COMMIT_CONFIG)

check: precommit test

fixtures-pipelines:
	if not exist .fixtures\pipelines mkdir .fixtures\pipelines
	xcopy /E /I /Y docs\examples\pipelines\* .fixtures\pipelines\
	@echo Copied docs\examples\pipelines into .fixtures\pipelines for local experimentation.

tester-present:
	where tester >nul 2>nul && (tester present $(TESTER_ARGS)) || ($(PYTHON) -m apps.tester present $(TESTER_ARGS))

smoke-onepiece:
	where tester >nul 2>nul && (tester --smoke $(TESTER_ARGS)) || ($(PYTHON) -m apps.tester --smoke $(TESTER_ARGS))
