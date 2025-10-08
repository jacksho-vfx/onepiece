# OnePiece configuration profiles

The `onepiece` CLI discovers configuration profiles from multiple locations to
provide defaults for commands like `aws ingest`. Profiles are defined in
`onepiece.toml` files and merged in the following order (lowest precedence
first):

1. **User configuration** – files located at:
   - `$XDG_CONFIG_HOME/onepiece/onepiece.toml` when `XDG_CONFIG_HOME` is set.
   - `~/.config/onepiece/onepiece.toml`
   - `~/.onepiece/onepiece.toml`
   - `~/onepiece.toml`
2. **Project configuration** – files located at either
   `<project-root>/onepiece.toml` or `<project-root>/.onepiece/onepiece.toml`.
   The project root defaults to the current working directory but can be
   overridden with the `ONEPIECE_PROJECT_ROOT` environment variable.
3. **Workspace configuration** – a `onepiece.toml` file stored inside the
   workspace folder that a command operates on (for example, the delivery folder
   passed to `onepiece aws ingest`).
4. **Command line arguments** – explicit options always override profile values.

Later files override earlier ones using deep-merge semantics, so a workspace
profile can change only a subset of values defined by the project or user
profiles.

Each configuration file can optionally define a `default_profile` key to select
which profile should be used when the CLI is invoked without `--profile`. The
value from the highest precedence file that specifies it wins. Profiles are
stored beneath the `[profiles]` table and may include general keys (such as
`project` and `show_code`) as well as command-specific tables like
`[profiles.mystudio.ingest]`:

```toml
default_profile = "mystudio"

[profiles.mystudio]
project = "Studio Project"
show_code = "STUDIO"
vendor_bucket = "vendor_in"
client_bucket = "client_in"

[profiles.mystudio.ingest]
max_workers = 8
resume = true
checkpoint_dir = "~/uploads/checkpoints"
```

When `onepiece aws ingest` runs, the CLI resolves the active profile using the
search order above, applies any overrides provided on the command line, and
passes the merged configuration to the ingest service. Other commands can reuse
these utilities to obtain consistent profile data.
