# Developer guide

> **Documentation refresh (November 2025):** Start here for an overview of the repository layout, bootstrap steps, and quality gates. The callouts below collect the topics teams search for most frequently so you can jump straight to the right section during onboarding or incident response.

## At a glance

- [Prerequisites](#prerequisites) — Confirm the tooling and credentials needed before cloning the repository.
- [Repository layout](#repository-layout) — Review the project structure before exploring the CLI entry points.
- [Bootstrapping a development environment](#bootstrapping-a-development-environment) — Follow the step-by-step setup commands, including virtual environment creation and dependency installation.

This guide describes how to set up a local development environment for OnePiece, explains how the repository is organised, and captures the day-to-day workflow for contributing changes.

> **Release spotlight (v1.0.0):** The CLI now resolves layered `onepiece.toml` profiles, the ingest helpers expose resumable upload controls, Trafalgar gains cache-tunable dashboards with render job management, and the new Uta Control Center turns the Typer command tree into a browser-based control room.
>
> **Latest merges:** Pipeline configuration now surfaces named definitions alongside profile data, the in-memory orchestrator gained a CLI and FastAPI surface for listing and triggering pipelines, and pipeline step factories can be extended through entry points. Perona's Wrangler automation added deadline escalations, cache rebuild recommendations, telemetry freshness checks, and render volatility spotlights so production leads can respond quickly. 【F:src/apps/onepiece/config.py†L1-L120】【F:src/apps/trafalgar/pipeline.py†L1-L194】【F:src/libraries/pipeline/plugins.py†L1-L120】【F:src/apps/perona/web/wrangler/scripts/production.py†L65-L420】【F:src/apps/perona/web/wrangler/scripts/telemetry.py†L191-L335】

## Prerequisites

- Python 3.12 or newer.
- Git and a GitHub account with access to the project.
- Access credentials for the services you plan to exercise locally (AWS, ShotGrid, etc.).

Optional tooling that streamlines development:

- [uv](https://github.com/astral-sh/uv) or [pipx](https://pipx.pypa.io/stable/) for managing virtual environments.
- Docker for validating integrations that depend on external services.

Maya-focused helpers lazily import PyMEL and surface friendly errors when the module is unavailable, so contributors can run the core test suite on machines without Autodesk software installed. Install the DCC-specific extras only when you need to exercise the integrations inside Maya itself. 【F:src/libraries/creative/dcc/maya/__init__.py†L1-L136】

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

   Workstations that rely on `pip install -r requirements.txt` now receive the
   same dependency set declared in `pyproject.toml`, so you can mirror the
   production footprint without enabling the development extras. 【F:requirements.txt†L1-L17】

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
   PYTHONPATH=src python -m apps.onepiece --help
   PYTHONPATH=src python -m apps.onepiece dcc publish --help
   ```

4. **Adhere to coding standards**. The project leans on Ruff and mypy for style and type safety. Avoid `print` statements in favour of the shared `structlog` logger pattern used across the CLIs (`structlog.get_logger(__name__)`) and prefer `Path` objects over string paths. When authoring new CLI commands, use the shared progress helpers described below so user-facing tools behave consistently. 【F:src/apps/onepiece/dcc/animation.py†L1-L25】【F:src/apps/onepiece/utils/progress.py†L1-L120】

5. **Run the quality suite** before opening a pull request. Continuous integration mirrors the commands listed earlier; matching the same sequence locally prevents surprises.

6. **Document user-facing changes**. Update the README, `CHANGELOG.md`, or create new docs inside `docs/` whenever you add new commands, flags, or workflows.

7. **Open a pull request** summarising your changes, screenshots, and any caveats. Link to relevant tickets and call out breaking changes explicitly.

## CLI utilities and UX guidelines

- **Progress reporting** – The Rich-powered progress tracker defined in `apps/onepiece/utils/progress.py` provides a consistent way to surface progress bars, success/failure banners, and task descriptions. Use it for long-running operations such as ingest, project setup, or delivery packaging.
- **ShotGrid workflows** – High-level commands such as `onepiece shotgrid show-setup` and `onepiece shotgrid deliver` wrap the lower-level client helpers. When extending these flows, reuse the convenience functions in `libraries/shotgrid` to stay aligned with existing retry logic and manifest generation.
- **DCC helpers** – Utilities under `apps/onepiece/dcc/` (for example `open_shot.py`) demonstrate the preferred pattern for validating input, mapping to `SupportedDCC` enums, and surfacing actionable CLI errors. Follow the same structure when introducing new DCC-facing commands.
- **Provider registry** – Trafalgar discovers delivery and reconciliation integrations through the `ProviderRegistry`. Register new providers via entry points rather than editing the built-ins so deployments can opt in without diverging from `main`. 【F:src/apps/trafalgar/providers/providers.py†L1-L210】

## Debugging tips

- `onepiece info` is a quick way to confirm that environment variables, DCC discovery, and AWS profiles are configured properly.
- `onepiece dcc animation debug-animation` highlights muted constraints and frame range issues without requiring Maya to render UI, making it ideal for quick validation on render nodes. 【F:src/apps/onepiece/dcc/animation.py†L1-L94】
- Tests inside `src/tests` include fixtures that mock AWS and ShotGrid interactions. Import them in new tests to avoid hitting live services.
- Use the `--dry-run` flags offered by the `aws` and `publish` commands to inspect their behaviour without transferring data.
- Enable structured logging by exporting `ONEPIECE_LOG_LEVEL=DEBUG` and `ONEPIECE_LOG_FORMAT=json` when you need machine-parseable telemetry for complex ingest or render investigations.
- The sample manifests under `docs/examples/` cover ingest, ShotGrid hierarchy seeding, render metrics, and Trafalgar event streams. Copy them into a throwaway directory so you can tweak values freely while testing edge cases.

## Launching demo surfaces for manual QA

The `tester` CLI bootstraps the Trafalgar, Perona, and Uta demo applications
alongside the pipeline API in one shot, preloading canned datasets and opening
the matching browser tabs. Run `tester present` during documentation reviews,
onboarding sessions, or UI regression tests when you need a predictable
environment without hitting live services. The command seeds pipeline demos,
verifies that `uvicorn` is available, cleans up stale processes bound to demo
ports, and exposes teardown helpers such as `tester close` for a clean slate.
Use `tester open --no-browser` to skip seeding and browser automation when
iterating locally. 【F:src/apps/tester/app.py†L1-L220】【F:src/apps/tester/presentation.py†L1-L220】

## Extending delivery integrations

- `DeliveryService` keeps a small LRU cache of delivery manifests keyed by `id`/`delivery_id`. When wiring a new provider, return a stable identifier so cache hits remain deterministic and consider increasing the `manifest_cache_size` argument when instantiating the service if the provider exposes a long delivery history.
- Cached manifests are cloned on read/write, so modifying the structures returned by `DeliveryService.list_deliveries` will not affect other requests. If you need to invalidate the cache (for example, after retrofitting a manifest on disk), call the `/admin/cache` flush endpoint or recreate the service instance within the FastAPI dependency overrides.

## Pipeline integration

The pipeline blueprint introduced in the latest release aligns the CLI, Trafalgar services, and Uta Control Center into a modular control plane that you can deploy incrementally. Start with the [pipeline overview](pipeline_overview.md) to compare reference architectures, required services, and integration patterns before wiring the components into your studio stack. Pair it with the [pipeline CLI guide](pipeline_cli.md) for command-level details, configuration loading tips, and plugin extension hooks.

### Required services at a glance

- **Control plane services** – Trafalgar (FastAPI) brokers ingest, render, delivery, and pipeline APIs, while Uta renders dashboards and mirrors CLI command trees for remote execution. Back both with PostgreSQL or SQLite for state plus Redis (or EventBridge/Kafka) when you need real-time fan-out. 【F:docs/pipeline_overview.md†L22-L64】【F:src/apps/trafalgar/web/pipeline.py†L1-L120】
- **Core integrations** – ShotGrid (REST + event streams) remains the primary production-tracking source of truth, object storage (S3/GCS/SMB) holds media packages, and render adapters (Deadline/Qube!/Tractor) surface farm telemetry. Provide scoped credentials to each surface and reuse existing SSO proxies where available. 【F:docs/pipeline_overview.md†L66-L108】
- **Telemetry and messaging** – Standardise on the message bus (Redis Streams, Kafka, SNS/SQS) highlighted in the overview so CLI hooks and Trafalgar webhooks can publish ingest/render events to your observability stack. 【F:docs/pipeline_overview.md†L110-L139】

### Wiring into legacy scheduling and asset-management systems

- **Scheduling adapters** – Use the CLI's render commands (`onepiece render submit`, `onepiece render status`, `onepiece render cancel`) alongside Trafalgar's render REST endpoints to bridge existing farm controllers. Script lightweight shims that translate legacy job payloads into the JSON contracts documented in the render guide, then feed responses back into your schedulers. When orchestrating multi-step flows, register them with the pipeline orchestrator so dashboards and automation can track runs centrally. 【F:docs/pipeline_overview.md†L88-L103】【F:docs/pipeline_cli.md†L1-L40】【F:src/apps/trafalgar/pipeline.py†L1-L194】
- **Asset-management hooks** – Map your asset/shot taxonomies into the configuration profiles referenced by the pipeline blueprint. The CLI validates OTIO timelines and ingest manifests against these profiles, while Trafalgar's provider registry exposes reconciliation webhooks that can push updates into legacy asset databases without forking the service. 【F:docs/pipeline_overview.md†L80-L89】【F:docs/pipeline_cli.md†L25-L38】
- **Event mirrors** – When your legacy stack already emits scheduling or asset events, subscribe Trafalgar to those channels or relay them through its webhook endpoints so dashboards and control surfaces stay in sync. Conversely, forward OnePiece events into the legacy bus to keep historical audit trails unified. 【F:docs/pipeline_overview.md†L110-L139】

### Key APIs and CLI entry points

- `onepiece pipeline list|describe|run|runs|run-status|watch` – Enumerate pipelines, inspect blueprints, trigger executions, review historical runs, and stream live status from either the embedded orchestrator or the Trafalgar API depending on environment flags. Use repeated `--param key=value` options to seed run parameters. 【F:src/apps/onepiece/pipeline/__init__.py†L158-L520】
- `/pipeline/pipelines`, `/pipeline/runs/{id}`, `/pipeline/runs/{id}/events` – FastAPI endpoints used by the Trafalgar CLI and dashboards. They list definitions, return run metadata, and stream server-sent events for live monitoring. 【F:src/apps/trafalgar/web/pipeline.py†L1-L120】
- `onepiece pipeline steps` entry-point group – Register custom pipeline steps in `pyproject.toml` so bespoke validation or delivery stages can be invoked without patching upstream code. 【F:docs/pipeline_cli.md†L25-L38】
- Trafalgar REST APIs – Leverage the ingest, render, and delivery endpoints surfaced by the control plane to automate manifests, farm orchestration, and reconciliation callbacks. Pin consumers to the versioned schemas called out in the overview and `docs/render_api.md`.
- Uta control widgets – Embed the Uta dashboards exposed in the overview into your orchestration stack for remote trigger and monitoring capabilities.

### Versioning and upgrade expectations

- OnePiece adheres to semantic versioning; pipeline schema changes land in minor releases with backwards-compatible defaults, while breaking API changes are reserved for major bumps. Watch the `CHANGELOG.md` for migration notes before upgrading orchestration runners. 【F:docs/developer_guide.md†L148-L197】
- Trafalgar's REST endpoints and CLI JSON outputs include explicit `schema_version` fields—keep consumers tolerant to at least one previous minor version so rolling upgrades across services remain seamless.
- When extending pipeline steps via entry points, version your custom packages independently and document compatible OnePiece ranges to help downstream teams coordinate upgrades. 【F:docs/pipeline_cli.md†L25-L38】

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
