"""Definition storage helpers for Trafalgar pipeline orchestration."""

from __future__ import annotations

import json
import traceback
from contextlib import contextmanager
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING, Any, Iterator, Mapping

import portalocker

if TYPE_CHECKING:  # pragma: no cover - import for typing only
    from .. import PipelineDefinition

__all__ = ["_serialise_exception", "PipelineDefinitionStore"]


def _serialise_exception(error: BaseException) -> dict[str, str]:
    """Return a serialisable payload describing *error*."""

    error_message = str(error) or error.__class__.__name__
    traceback_text = "".join(
        traceback.format_exception(type(error), error, error.__traceback__)
    )
    return {
        "error": error_message,
        "error_type": type(error).__name__,
        "error_message": error_message,
        "traceback": traceback_text,
    }


class PipelineDefinitionStore:
    """Persist pipeline definitions to a JSON file on disk."""

    def __init__(self, *, path: str | Path | None = None) -> None:
        if path is None or str(path) == ":memory:":
            self._path: Path | None = None
            self._file_lock_path: Path | None = None
        else:
            resolved = Path(path)
            resolved.parent.mkdir(parents=True, exist_ok=True)
            self._path = resolved
            self._file_lock_path = resolved.with_suffix(resolved.suffix + ".lock")
        self._lock = Lock()
        self._definitions: dict[str, dict[str, Any]] = self._load_definitions()

    def list_definitions(self) -> tuple["PipelineDefinition", ...]:
        with self._lock:
            payloads = [dict(payload) for payload in self._definitions.values()]
        definitions = []
        for payload in payloads:
            from .. import pipeline_definition_from_serialised

            definitions.append(pipeline_definition_from_serialised(payload))
        return tuple(definitions)

    def save(self, definition: "PipelineDefinition") -> None:
        payload = dict(definition.serialise())
        with self._lock:
            self._definitions[definition.name] = payload
            self._write_locked()

    def remove(self, name: str) -> None:
        with self._lock:
            removed = self._definitions.pop(name, None)
            if removed is None:
                return
            self._write_locked()

    def _load_definitions(self) -> dict[str, dict[str, Any]]:
        path = self._path
        if path is None:
            return {}
        with self._file_lock(shared=True):
            if not path.exists():
                return {}
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                return {}
        if not text.strip():
            return {}
        try:
            payload = json.loads(text)
        except (TypeError, ValueError):
            return {}

        data: Any
        if isinstance(payload, Mapping):
            definitions_section = payload.get("definitions")
            if isinstance(definitions_section, Mapping):
                data = definitions_section
            elif isinstance(definitions_section, list):
                data = definitions_section
            else:
                data = payload
        else:
            data = payload

        definitions: dict[str, dict[str, Any]] = {}
        if isinstance(data, Mapping):
            for name, entry in data.items():
                if not isinstance(entry, Mapping):
                    continue
                definitions[str(name)] = dict(entry)
        elif isinstance(data, list):
            for entry in data:
                if not isinstance(entry, Mapping):
                    continue
                name = entry.get("name")
                if not isinstance(name, str) or not name:
                    continue
                definitions[name] = dict(entry)
        return definitions

    def _write_locked(self) -> None:
        if self._path is None:
            return
        serialisable = {
            name: payload for name, payload in sorted(self._definitions.items())
        }
        document = {"definitions": serialisable}
        tmp_path = self._path.with_suffix(self._path.suffix + ".tmp")
        with self._file_lock(shared=False):
            try:
                tmp_path.write_text(
                    json.dumps(document, indent=2, sort_keys=True),
                    encoding="utf-8",
                )
                tmp_path.replace(self._path)
            finally:
                try:
                    tmp_path.unlink(missing_ok=True)
                except OSError:
                    pass

    @contextmanager
    def _file_lock(self, *, shared: bool) -> Iterator[None]:
        lock_path = self._file_lock_path
        if lock_path is None:
            yield
            return
        flags = portalocker.LOCK_SH if shared else portalocker.LOCK_EX
        with portalocker.Lock(lock_path, mode="a+", flags=flags):
            yield
