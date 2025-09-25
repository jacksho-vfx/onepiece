# OnePiece Changelog

All notable changes to the OnePiece pipeline toolkit.

---

## [v0.2.0] – Current Release

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
- Bulk operations for versions, playlists, tasks.
- Retry and error handling for API calls.
- Optional: template-based hierarchy cloning.

**DCC Client**
- Direct S3/cloud publishing support.
- Plugin or asset checks per DCC.

**AWS / s5cmd**
- Transfer reports (uploaded/skipped/failed).
- Multipart or resumable uploads for large files.
- Optional preflight of bucket structure.

**CLI / Usability**
- Progress bars or structured CLI feedback for long-running tasks.
- Improved error messages and structured exit codes.

**Testing / CI**
- CLI tests for main commands (`show-setup`, `upload-version`, `aws sync`, `validate`).
- Mocking for ShotGrid/S3/DCC environments in CI.
- Coverage reporting.

**Documentation**
- Example CSV for `show-setup`.
- CLI usage examples for AWS and DCC.
- Developer guide (optional for v0.1).

---

## [v0.1.0] – Initial Release & Setup

- Project scaffolding created.
- Initial GitHub workflows added.
- Basic Makefile targets (`format`, `lint`, `typecheck`, `test`, `check`).
- Repository tooling and environment setup (`.venv`, `.gitignore`, logging, configs).
- README and Changelog introduced.
