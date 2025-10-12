# Developer guide

This guide describes how to set up a local development environment for OnePiece, explains how the repository is organised, and captures the day-to-day workflow for contributing changes.

> **Release spotlight (v1.0.0):** The CLI now resolves layered `onepiece.toml` profiles, the ingest helpers expose resumable upload controls, Trafalgar gains cache-tunable dashboards with render job management, and the new Uta Control Center turns the Typer command tree into a browser-based control room.

## Prerequisites

- Python 3.12 or newer.
- Git and a GitHub account with access to the project.
- Access credentials for the services you plan to exercise locally (AWS, ShotGrid, etc.).

Optional tooling that streamlines development:

- [uv](https://github.com/astral-sh/uv) or [pipx](https://pipx.pypa.io/stable/) for managing virtual environments.
- Docker for validating integrations that depend on external services.

## Repository layout

```
onepiece/
├── src/
│   ├── apps/                # Typer-based CLI entry points and command groups
│   ├── libraries/           # Reusable business logic shared by the CLI commands
│   └── tests/               # Unit tests, fixtures, and sample data
├── docs/                    # Onboarding guides, walkthroughs, and sample assets
├── requirements.txt         # Production dependency lock for workstation installs
├── pyproject.toml           # Project metadata and optional dependency groups
└── README.md                # High-level overview and quick-start instructions
```

## Bootstrapping a development environment

1. **Clone the repository** and create a virtual environment:

   ```bash
   git clone https://github.com/<your-org>/onepiece.git
   cd onepiece
   python -m venv .venv
   source .venv/bin/activate
   ```

2. **Install dependencies** in editable mode. The `dev` extra pulls in tools for linting, type-checking, and testing:

   ```bash
   pip install -e .[dev]
   ```

3. **Configure service credentials**. Export the environment variables documented in the top-level README under *Configuring integrations*.

4. **Run the verification suite** to ensure your environment is healthy:

   ```bash
   pytest
   ruff check src tests
   mypy
   ```

   Running these commands before you start coding validates that your interpreter, dependencies, and external integrations are all wired correctly.

## Development workflow

1. **Create a feature branch**:

   ```bash
   git checkout -b feature/<ticket-or-topic>
   ```

2. **Write tests and code**. Keep business logic inside `src/libraries` and restrict CLI-specific concerns (argument parsing, console output) to `src/apps`.

3. **Use the in-repo CLI for rapid feedback**. While iterating, run commands directly from the source tree:

   ```bash
   python -m src.apps.onepiece --help
   python -m src.apps.onepiece publish --help
   ```

4. **Adhere to coding standards**. The project leans on Ruff and mypy for style and type safety. Avoid `print` statements in favour of the shared logging utilities inside `src/libraries/logging` and prefer `Path` objects over string paths. When authoring new CLI commands, use the shared progress helpers described below so user-facing tools behave consistently.

5. **Run the quality suite** before opening a pull request. Continuous integration mirrors the commands listed earlier; matching the same sequence locally prevents surprises.

6. **Document user-facing changes**. Update the README, `CHANGELOG.md`, or create new docs inside `docs/` whenever you add new commands, flags, or workflows.

7. **Open a pull request** summarising your changes, screenshots, and any caveats. Link to relevant tickets and call out breaking changes explicitly.

## CLI utilities and UX guidelines

- **Progress reporting** – The Rich-powered progress tracker defined in `apps/onepiece/utils/progress.py` provides a consistent way to surface progress bars, success/failure banners, and task descriptions. Use it for long-running operations such as ingest, project setup, or delivery packaging.
- **ShotGrid workflows** – High-level commands such as `onepiece shotgrid show-setup` and `onepiece shotgrid deliver` wrap the lower-level client helpers. When extending these flows, reuse the convenience functions in `libraries/shotgrid` to stay aligned with existing retry logic and manifest generation.
- **DCC helpers** – Utilities under `apps/onepiece/dcc/` (for example `open_shot.py`) demonstrate the preferred pattern for validating input, mapping to `SupportedDCC` enums, and surfacing actionable CLI errors. Follow the same structure when introducing new DCC-facing commands.

## Debugging tips

- `onepiece info` is a quick way to confirm that environment variables, DCC discovery, and AWS profiles are configured properly.
- Tests inside `src/tests` include fixtures that mock AWS and ShotGrid interactions. Import them in new tests to avoid hitting live services.
- Use the `--dry-run` flags offered by the `aws` and `publish` commands to inspect their behaviour without transferring data.
- Enable structured logging by exporting `ONEPIECE_LOG_LEVEL=DEBUG` and `ONEPIECE_LOG_FORMAT=json` when you need machine-parseable telemetry for complex ingest or render investigations.
- The sample manifests under `docs/examples/` cover ingest, ShotGrid hierarchy seeding, render metrics, and Trafalgar event streams. Copy them into a throwaway directory so you can tweak values freely while testing edge cases.

## Extending delivery integrations

- `DeliveryService` keeps a small LRU cache of delivery manifests keyed by `id`/`delivery_id`. When wiring a new provider, return a stable identifier so cache hits remain deterministic and consider increasing the `manifest_cache_size` argument when instantiating the service if the provider exposes a long delivery history.
- Cached manifests are cloned on read/write, so modifying the structures returned by `DeliveryService.list_deliveries` will not affect other requests. If you need to invalidate the cache (for example, after retrofitting a manifest on disk), call the `/admin/cache` flush endpoint or recreate the service instance within the FastAPI dependency overrides.

## Releasing changes

1. Bump the version in `pyproject.toml` following semantic versioning.
2. Update `CHANGELOG.md`, the README, and any other user-facing docs with a summary of noteworthy changes.
3. Build and publish the package:

   ```bash
   python -m build
   twine upload dist/*
   ```

4. Tag the release in Git and push the tag to the remote repository.

Following this workflow keeps local development predictable and ensures new contributors can ramp up quickly.

## Code review checklist

Before opening a pull request, confirm the following items to keep reviews
snappy:

- [ ] All new modules include docstrings summarising their intent and expected usage.
- [ ] CLI help text and option descriptions are clear, concise, and reference configuration profiles where appropriate.
- [ ] User-facing changes are documented in the README or `docs/` so operators understand the impact.
- [ ] Tests cover the happy path and representative failure cases, especially around integrations.
- [ ] `CHANGELOG.md` includes a bullet describing any noteworthy behaviour change.

## Maintaining local data fixtures

Reusable fixtures speed up exploratory development. The repository provides a
`make fixtures` target that copies canonical CSV manifests, OTIO files, and
render metrics into `.fixtures/` under your project root. Run it after pulling a
branch that introduces new example assets:

```bash
make fixtures
```

The Makefile task is idempotent and will refresh existing fixtures with the
latest revisions from `docs/examples/`. Point integration tests or sandbox runs
at `.fixtures/` to avoid editing files tracked in Git.
