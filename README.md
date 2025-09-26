# OnePiece

OnePiece is a Typer-powered command line toolkit designed for ingesting, packaging, and publishing media assets across digital content creation (DCC) tools and production tracking systems. It bundles high-level pipeline commands—such as AWS S3 synchronisation, ShotGrid setup utilities, and DCC publishing helpers—into a single CLI that can be embedded inside a studio workflow.

## Quick start

```bash
# Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows use: .venv\\Scripts\\activate

# Install the CLI and its core dependencies
pip install -e .

# Explore the available commands
onepiece --help
```

Once installed, the CLI exposes a number of subcommands:

- `onepiece info` &mdash; Prints information about the current environment, detected DCCs, and ShotGrid/AWS configuration hints.
- `onepiece greet NAME` &mdash; A smoke-test command to confirm the CLI is wired up.
- `onepiece publish ...` &mdash; Packages scene renders, previews, and metadata and pushes them to S3 (see the detailed options below).
- `onepiece ingest` and `onepiece aws ...` &mdash; Entry points for synchronising media to and from AWS S3 buckets.
- `onepiece validate ...` &mdash; Runs validation suites for ingest/publish workflows.

Use `onepiece COMMAND --help` to inspect options for any command.

## Requirements

- Python 3.9 or newer
- Access to the required DCC tools on the machine running the CLI
- Credentials for any external integrations you plan to use (e.g. AWS profiles, ShotGrid API scripts)

## Installation

### From PyPI (recommended for workstations)

If you just need the CLI, install it directly from PyPI into an isolated environment:

```bash
python -m venv ~/.venvs/onepiece
source ~/.venvs/onepiece/bin/activate
pip install onepiece
```

### From source (for development or custom builds)

Clone the repository and install it in editable mode. The `dev` extras include linting and test tooling useful during development.

```bash
git clone https://github.com/<your-org>/onepiece.git
cd onepiece
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
```

To keep dependencies fresh, re-run `pip install -e .[dev]` after changing branches or updating `pyproject.toml`.

## Configuring integrations

Many commands rely on environment variables that map to your studio&rsquo;s infrastructure. Export them in your shell profile or pass them inline before running the CLI.

### ShotGrid

Set the variables required by the ShotGrid API client:

```bash
export ONEPIECE_SHOTGRID_URL="https://mystudio.shotgrid.autodesk.com"
export ONEPIECE_SHOTGRID_SCRIPT="pipeline-user"
export ONEPIECE_SHOTGRID_KEY="<script-key>"
```

You can verify the configuration with `onepiece info`.

#### Bulk ShotGrid helpers

The lightweight in-memory ShotGrid client that ships with the toolkit now
supports production-ready features for dealing with large deliveries:

- **Bulk operations** – create, update, or delete batches of entities with a
  single call.  The helpers automatically fan-out into the minimal number of API
  requests and share the same retry policy used by the rest of the client.
- **Resilient retries** – transient failures trigger exponential backoff with
  jitter and actionable log messages so that operators understand what happened
  and when the next attempt will fire.
- **Hierarchy templates** – declare entity trees (episodes, scenes, shots, …)
  once and apply them to new projects in a single command.  This drastically
  reduces the time it takes to bootstrap a show.

See ``libraries.shotgrid.client`` for usage examples and the accompanying unit
tests for end-to-end demonstrations of the new capabilities.

### AWS

The AWS commands leverage the standard AWS CLI configuration. Configure credentials via `aws configure`, or specify a profile when running commands:

```bash
onepiece aws sync-from --bucket my-bucket --show-code SHOW --folder plates --local-path /data/plates --profile studio-prod
```

## Working with the CLI

### Publishing DCC packages

The `publish` command gathers renders, previews, and metadata produced by a DCC and uploads a packaged result to S3.

```bash
onepiece publish \
  --dcc maya \
  --scene-name seq010_sh010_lighting_v002 \
  --renders /projects/show/renders/latest \
  --previews /projects/show/previews/latest.mov \
  --otio /projects/show/edit/shot.otio \
  --metadata /tmp/publish.json \
  --destination /tmp/output_package \
  --bucket studio-prod-data \
  --show-code SHOW \
  --show-type vfx
```

The command validates the target DCC, loads metadata from JSON, and reports the final package path once complete.

### AWS synchronisation helpers

`onepiece aws sync-from` and `onepiece aws sync-to` wrap the data movers that mirror folders between local storage and S3. Both commands accept `--include/--exclude` globs and a `--dry-run` flag for auditing transfers.

### Inspecting your environment

`onepiece info` prints helpful debugging information such as Python version, active AWS profile, configured ShotGrid URL, and detected DCCs in the current `PATH`. This is a useful first command when onboarding a new workstation.

## Running the CLI from source

During development you can execute the application without installing it by running the module directly:

```bash
python -m src.apps.onepiece --help
```

This respects the same environment variables as the installed entry point and is convenient while iterating on code.

## Contributing

1. Fork and clone the repository.
2. Create a virtual environment and install dependencies with `pip install -e .[dev]`.
3. Run the quality suite before submitting changes:
   - `pytest`
   - `ruff check src tests`
   - `mypy`
4. Open a pull request with a description of your changes and any relevant screenshots or logs.

## Getting help

If you run into issues, open an issue in this repository with the command you ran and the resulting output. Include your OS, Python version, and whether you installed from PyPI or source to help us reproduce the problem quickly.
