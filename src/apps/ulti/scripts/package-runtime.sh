#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON_DIR="$ROOT_DIR/python"

RUNTIME_SRC=${PYTHON_RUNTIME_SOURCE:-"$ROOT_DIR/artifacts/runtime"}
WHEELS_SRC=${PYTHON_WHEELS_SOURCE:-"$ROOT_DIR/artifacts/wheels"}
DCC_SRC=${DCC_BRIDGE_SOURCE:-"$ROOT_DIR/artifacts/dcc-bridges"}

copy_payload() {
  local source_dir="$1"
  local target_dir="$2"
  local label="$3"

  if [[ ! -d "$source_dir" ]]; then
    echo "[package-runtime] Missing ${label} payload at ${source_dir}" >&2
    exit 1
  fi

  mkdir -p "$target_dir"
  echo "[package-runtime] Copying ${label} from ${source_dir} to ${target_dir}"
  rsync -a --delete "$source_dir"/ "$target_dir"/
}

prepare_manifest() {
  local manifest_path="$1"
  cat >"$manifest_path" <<MANIFEST
{
  "generatedAt": "$(date --iso-8601=seconds)",
  "runtimeSource": "$RUNTIME_SRC",
  "wheelsSource": "$WHEELS_SRC",
  "dccBridgeSource": "$DCC_SRC"
}
MANIFEST
}

main() {
  mkdir -p "$PYTHON_DIR"

  copy_payload "$RUNTIME_SRC" "$PYTHON_DIR/runtime" "Python runtime"
  copy_payload "$WHEELS_SRC" "$PYTHON_DIR/wheels" "pipeline wheels"
  copy_payload "$DCC_SRC" "$PYTHON_DIR/dcc" "DCC bridge scripts"

  prepare_manifest "$PYTHON_DIR/manifest.json"
  echo "[package-runtime] Python runtime bundle prepared at $PYTHON_DIR"
}

main "$@"
