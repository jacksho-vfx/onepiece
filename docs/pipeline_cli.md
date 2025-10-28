# OnePiece pipeline CLI

The `onepiece pipeline` command group provides a home for the upcoming pipeline
orchestrator integration. The interface is available today so teams can begin
writing automation and documentation against a stable surface while the
orchestrator service is finalized.

## Getting started

```console
$ onepiece pipeline --help
```

The help output lists the subcommands that will eventually proxy orchestrator
operations:

- `list` – enumerate the pipelines registered with the orchestrator.
- `describe` – show the configuration and current status for a single pipeline.
- `run` – trigger a pipeline execution, optionally providing parameters via
  repeated `--param key=value` options.

Each command currently emits a placeholder message. Replace the placeholders
with calls to the orchestrator client as soon as the service API is available.

## Extending pipeline steps via plugins

Studios can register additional pipeline steps without modifying the OnePiece
codebase by publishing entry points under the
`onepiece.pipeline_steps` group. Each entry maps a name to a
``PipelineStepFactory`` callable that accepts a configuration mapping and
returns a :class:`libraries.pipeline.models.PipelineStep` instance.

```toml
[project.entry-points."onepiece.pipeline_steps"]
episode-qc = "studio_pkg.pipeline:episode_qc_step"
```

The loader exposed at :func:`libraries.pipeline.discover_pipeline_step_factories`
validates that every entry point resolves to a callable factory and raises
actionable errors when optional dependencies are missing. Factories shipped
within OnePiece take precedence over third-party plugins—use unique names to
avoid conflicts. This keeps built-in behaviour predictable while still letting
deployments opt into custom automation.
