# OnePiece Changelog

All notable changes to the OnePiece pipeline toolkit.

---

## [Unreleased]

_No changes yet._

---

## [v0.7.0] – Current Release

### Added / Improved

**ShotGrid Bulk Operations**
- Added a shared JSON/YAML loader that powers the bulk playlist and version
  Typer commands so automation payloads can be expressed in either format.
- Mirrored the structured input handling used by `deliver.py` to keep
  workflows consistent across the ShotGrid CLI surface.

**Hierarchy Templates**
- Implemented template serialisation/deserialisation in the ShotGrid client and
  exposed `onepiece shotgrid templates save` / `apply` commands for capturing
  and replaying hierarchies from disk.

**Quality**
- Expanded the ShotGrid bulk CLI tests to cover YAML inputs and the new
  template persistence flows, ensuring regressions surface before release.

---

## [v0.6.0] – Previous Release

### Added / Improved

**CLI Progress Tracking**
- Adopted the shared `progress_tracker` helper in the ShotGrid delivery and validation CLIs so long-running packaging and reconciliation jobs surface consistent Rich progress output.

**ShotGrid Delivery**
- Replaced the legacy Typer progress bar with detailed per-version packaging updates and wired S3 synchronisation into the tracker so operators can follow `s5cmd` activity without switching panes.

**Release Management**
- Bumped project metadata, README highlights, and supporting docs to advertise v0.6.0, keeping published guidance aligned with the packaged code.

---

## [v0.5.0] – Previous Release

### Added / Improved

**ShotGrid Delivery**
- Introduced a `onepiece shotgrid deliver` workflow that assembles approved
  versions into MediaShuttle-ready ZIP archives, emits JSON/CSV manifests, and
  syncs the payload to the appropriate S3 context.

**Media Ingest**
- Refreshed `onepiece aws ingest` with rich progress feedback shared with other
  long-running commands so operators can monitor validation and upload activity
  in real time.

**DCC Utilities**
- Added `onepiece dcc open-shot` for opening scene files directly from the CLI
  with automatic DCC detection based on the file extension.

**Developer Experience**
- Exposed a reusable progress tracker for CLI commands, helping new utilities
  present consistent status messages and success/failure reporting.

**Documentation**
- Expanded the README and developer guide to cover the new delivery, ingest,
  and DCC helpers alongside guidance on integrating the shared progress tools.

---

## [v0.4.0] – Previous Release

### Added / Improved

**Release Management**
- Bumped all version metadata to v0.4.0 so the CLI, library modules, and packaging configuration report the same release number.

**Documentation**
- Refreshed the README highlights for v0.4.0 and clarified the current/previous release history.
- Tidied the changelog to keep earlier milestones intact while spotlighting the latest release.

---

## [v0.3.0] – Previous Release

### Added / Improved

**ShotGrid Client**
- Added generic bulk create/update/delete helpers with exponential backoff so that large entity batches complete reliably even when the API flakes.  All higher-level helpers now route through the shared retry logic.
- Introduced hierarchy template application that seeds a project and injects template-provided attributes while fanning out through the new bulk utilities.
- Expanded review tooling with playlist registration and lookup helpers to keep curated version sets in sync with ShotGrid.

**AWS / S3**
- The `s5cmd` wrapper now prints transfer summaries that include total, uploaded, skipped, and failed file counts, while surfacing actionable errors when the command exits non-zero.
- Normalised path handling ensures trailing slashes are preserved for both S3 and local targets, preventing duplicated segments in generated sync commands.

**Documentation**
- Added a comprehensive developer guide that covers repository layout, workflows, and release procedures.
- Published CLI walkthroughs with sample CSV manifests that showcase ingest, publish, and ShotGrid bootstrap flows.
- Bundled reusable example assets under `docs/examples/` for safe sandbox testing.

---

## [v0.2.0] – Previous Release

### Added / Implemented

**Core CLI Commands**
- `onepiece show-setup`: Create ShotGrid project hierarchy from CSV.
- `onepiece upload-version`: Upload media and create missing ShotGrid entities.
- `onepiece dcc open`: Open scenes in supported DCCs (Nuke, Maya, Blender, Houdini, 3ds Max).
- `onepiece aws sync-to / sync-from`: Sync media using `s5cmd` with dry-run and include/exclude filters.
- `onepiece validate`: Validate filesystem preflight, naming conventions, and basic DCC environment checks.

**ShotGrid Client**
- `get_or_create` helpers for Project, Episode, Scene, Shot, Version, Playlist.
- Caching for repeated API calls.
- Support for create/get operations for projects, episodes, scenes, shots, versions, tasks, and playlists.

**DCC Client**
- Open scene (`open_scene`) and batch open (`batch_open_scenes`) for 5 major DCCs.
- Environment checks (`is_dcc_installed`, `check_dcc_environment`).
- Save scene helper with overwrite protection.
- Publish scene with optional metadata sidecar (ShotGrid IDs, episode, scene, shot, asset).

**AWS / S3**
- `s5cmd` based sync for vendor/client contexts.
- Context-aware paths for VFX and prod (`vendor_in/out`, `client_in/out`).
- Dry-run, include/exclude filtering implemented.

**Validations**
- Filesystem preflight: existence, writability, disk space.
- Naming conventions for show, episode, scene, shot, shot_name, asset_name.
- DCC environment validation (installed DCC, Python version, GPU).
- Initial asset consistency validation for local filesystem.

**Models / XData**
- Project, Episode, Scene, Shot, Version, Asset with entity type defaults.

**Repo & Tooling**
- Absolute imports throughout the repo.
- Config via environment variables.
- Logging with `structlog`.
- GitHub workflows for formatting (black, isort), linting, and tests.
- Release packaging via tar + install script.
- README and initial Changelog added.

**Testing**
- Unit tests for ShotGrid client (`get_or_create`), DCC client, and validations library.
- Pytest fixtures for temporary filesystem and mocks for external services.

---

### Coming Soon / To Do

**Validations**
- Full asset consistency checks against S3.
- Batch CSV / directory naming validation for all shots/assets.
- Extended DCC environment validation (plugins, GPU details per DCC).

**ShotGrid Client**
- Expose playlist and version bulk helpers via dedicated CLI commands.
- Persist hierarchy templates to disk formats (YAML/JSON) for reuse across shows.

**DCC Client**
- Direct S3/cloud publishing support.
- Plugin or asset checks per DCC.

**AWS / s5cmd**
- Multipart or resumable uploads for large files.
- Optional preflight of bucket structure.

**CLI / Usability**
- Progress bars or structured CLI feedback for long-running tasks.
- Improved error messages and structured exit codes.

**Testing / CI**
- CLI tests for main commands (`show-setup`, `upload-version`, `aws sync`, `validate`).
- Mocking for ShotGrid/S3/DCC environments in CI.
- Coverage reporting.

---

## [v0.1.0] – Initial Release & Setup

- Project scaffolding created.
- Initial GitHub workflows added.
- Basic Makefile targets (`format`, `lint`, `typecheck`, `test`, `check`).
- Repository tooling and environment setup (`.venv`, `.gitignore`, logging, configs).
- README and Changelog introduced.
