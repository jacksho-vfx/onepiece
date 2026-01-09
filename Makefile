.PHONY: setup format lint typecheck test precommit install-precommit check fixtures-pipelines tester-present install-dev check-format smoke-onepiece

ifeq ($(OS),Windows_NT)
VENV_BIN := .venv\Scripts
PYTHON ?= $(VENV_BIN)\python.exe
PIP ?= $(VENV_BIN)\pip.exe
RM_VENV := if exist .venv rmdir /s /q .venv
FIXTURES_DIR := .fixtures\pipelines
FIXTURES_MKDIR := if not exist $(FIXTURES_DIR) mkdir $(FIXTURES_DIR)
FIXTURES_COPY := xcopy /E /I /Y docs\examples\pipelines\* $(FIXTURES_DIR)\
TESTER_PRESENT := where tester >nul 2>nul && (tester present $(TESTER_ARGS)) || ($(PYTHON) -m apps.tester present $(TESTER_ARGS))
TESTER_SMOKE := where tester >nul 2>nul && (tester --smoke $(TESTER_ARGS)) || ($(PYTHON) -m apps.tester --smoke $(TESTER_ARGS))
else
VENV_BIN := .venv/bin
PYTHON ?= $(VENV_BIN)/python
PIP ?= $(VENV_BIN)/pip
RM_VENV := rm -rf .venv
FIXTURES_DIR := .fixtures/pipelines
FIXTURES_MKDIR := mkdir -p $(FIXTURES_DIR)
FIXTURES_COPY := cp -R docs/examples/pipelines/. $(FIXTURES_DIR)
TESTER_PRESENT := command -v tester >/dev/null 2>&1 && tester present $(TESTER_ARGS) || $(PYTHON) -m apps.tester present $(TESTER_ARGS)
TESTER_SMOKE := command -v tester >/dev/null 2>&1 && tester --smoke $(TESTER_ARGS) || $(PYTHON) -m apps.tester --smoke $(TESTER_ARGS)
endif
PRE_COMMIT ?= $(PYTHON) -m pre_commit
PRE_COMMIT_CONFIG ?= .pre-commit-config.yaml
TESTER_ARGS ?=

$(PYTHON):
	python -m venv .venv

setup: $(PYTHON)
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -r requirements.txt

check-format:
	$(PYTHON) -m black --check src

format:
	$(PYTHON) -m black src

lint:
	$(PYTHON) -m ruff check src

typecheck:
	$(PYTHON) -m mypy

test:
	$(PYTHON) -m pytest --maxfail=1 --disable-warnings -q

install-dev:
	$(RM_VENV)
	python -m venv .venv
	$(PIP) install -U pip
	$(PIP) install -e .[dev]

precommit:
	$(PRE_COMMIT) run --all-files --show-diff-on-failure --config $(PRE_COMMIT_CONFIG)

install-precommit:
	$(PRE_COMMIT) install --config $(PRE_COMMIT_CONFIG)

check: precommit test

fixtures-pipelines:
	$(FIXTURES_MKDIR)
	$(FIXTURES_COPY)
	@echo Copied docs\examples\pipelines into .fixtures\pipelines for local experimentation.

tester-present:
	$(TESTER_PRESENT)

smoke-onepiece:
	$(TESTER_SMOKE)
