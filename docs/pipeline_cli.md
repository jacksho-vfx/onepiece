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
