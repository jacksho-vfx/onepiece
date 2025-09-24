.PHONY: format lint typecheck test check

format:
 black onepiece
 ruff --fix onepiece

lint:
 ruff onepiece

typecheck:
 mypy onepiece --strict

test:
 pytest --maxfail=1 --disable-warnings -q

check: format lint typecheck test
