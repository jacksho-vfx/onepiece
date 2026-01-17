# Dedupe Report

## Scope
- Root scanned: `src/libraries`
- Languages: Python

### Exclusions
- Dependency/build outputs: `node_modules/`, `vendor/`, `dist/`, `build/`, `out/`, `.next/`, `.turbo/`, `coverage/`, `target/`, `bin/`, `obj/`
- Any directory named `generated` or `migrations`

## Phase 1 — Inventory & Detection
### Exact duplicates
- Several empty `__init__.py` files share identical content:
  - `src/libraries/automation/dailies/__init__.py`
  - `src/libraries/creative/dcc/anima/__init__.py`
  - `src/libraries/onepiece/cli/misc/__init__.py`
  - `src/libraries/platform/handlers/__init__.py`
  - `src/libraries/platform/media/ffmpeg/__init__.py`

These are empty module markers; no consolidation planned because removing them could change package semantics.

### Near duplicates
- `src/libraries/creative/dcc/max/deploy.py`
- `src/libraries/creative/dcc/unreal/deploy.py`
- `src/libraries/creative/dcc/maya/deploy.py`
- `src/libraries/creative/dcc/nuke/deploy.py`

These share the same deployment and script-copying logic with small differences (default paths, file filters, and log event names).

### Common helper candidates
- `copy_scripts_to` helper appears in multiple DCC deploy modules with identical implementation.

## Phase 2 — Plan
- Canonical implementation: create a shared helper module under `src/libraries/creative/dcc/` for deployment and script copying utilities.
- Strategy: replace repeated implementations with imports/wrappers in the DCC-specific deploy modules to keep public APIs intact.

## Phase 3 — Refactor
- Consolidated shared DCC deploy helpers into `src/libraries/creative/dcc/deploy_utils.py`.
  - Canonical implementation chosen because the deploy logic is identical across DCC integrations with only constants/predicates differing.
  - `copy_scripts_to`, script listing logic, and deployment copy logic now live in the shared helper.
  - Updated call sites:
    - `src/libraries/creative/dcc/max/deploy.py`
    - `src/libraries/creative/dcc/unreal/deploy.py`
    - `src/libraries/creative/dcc/maya/deploy.py`
    - `src/libraries/creative/dcc/nuke/deploy.py`
  - Public APIs preserved: module-level functions remain and forward to shared helpers.

## Phase 4 — Validation
- Formatting: `make format` (pass)
- Lint: `make lint` (pass)
- Type check: `make typecheck` (pass)
- Tests: `make test` (pass; 1263 passed, 4 skipped)
