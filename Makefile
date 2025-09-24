.PHONY: format lint typecheck test precommit install-precommit check

PYTHON ?= python3
PRE_COMMIT ?= $(PYTHON) -m pre_commit
PRE_COMMIT_CONFIG ?= .pre_commit_config.yaml

format:
black src
ruff --fix src

lint:
ruff src

typecheck:
mypy src/onepiece --strict

test:
	pytest --maxfail=1 --disable-warnings -q

precommit:
	$(PRE_COMMIT) run --all-files --show-diff-on-failure --config $(PRE_COMMIT_CONFIG)

install-precommit:
	$(PRE_COMMIT) install --config $(PRE_COMMIT_CONFIG)

check: precommit test
