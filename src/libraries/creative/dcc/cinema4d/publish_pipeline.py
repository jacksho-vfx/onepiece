"""Scene validation and publishing helpers for the Cinema 4D panel."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Mapping, MutableMapping, Sequence

import structlog


log = structlog.get_logger(__name__)

ValidatorOptions = Mapping[str, Any]


def _normalise_sequence(value: Any) -> tuple[Any, ...]:
    if value is None:
        return ()
    if isinstance(value, (list, tuple, set)):
        return tuple(value)
    return (value,)


@dataclass
class RenderLayer:
    """Represent a render layer that can be toggled for output."""

    name: str
    renderable: bool = True


@dataclass
class Take:
    """Represent a Cinema 4D take that can be rendered."""

    name: str
    renderable: bool = True


@dataclass
class SceneContext:
    """Contextual data describing the current Cinema 4D scene."""

    show: str
    shot: str
    scene_path: Path
    version: int = 1
    asset: str | None = None
    task: str | None = None
    user: str | None = None
    frame_range: tuple[int, int] | None = None
    expected_frame_range: tuple[int, int] | None = None
    textures: tuple[Path, ...] = ()
    caches: tuple[Path, ...] = ()
    texture_color_spaces: Mapping[Path, str] = field(default_factory=dict)
    render_layers: tuple[RenderLayer, ...] = ()
    takes: tuple[Take, ...] = ()

    def with_updates(self, payload: Mapping[str, Any]) -> "SceneContext":
        """Return a copy of the context patched by ``payload``."""

        data: MutableMapping[str, Any] = {
            "show": self.show,
            "shot": self.shot,
            "scene_path": self.scene_path,
            "version": self.version,
            "asset": self.asset,
            "task": self.task,
            "user": self.user,
            "frame_range": self.frame_range,
            "expected_frame_range": self.expected_frame_range,
            "textures": self.textures,
            "caches": self.caches,
            "texture_color_spaces": self.texture_color_spaces,
            "render_layers": self.render_layers,
            "takes": self.takes,
        }

        if "scene_path" in payload:
            data["scene_path"] = Path(str(payload["scene_path"]))
        if "version" in payload:
            try:
                data["version"] = int(payload["version"])
            except (TypeError, ValueError):
                log.warning(
                    "cinema4d_scene_validator.invalid_version",
                    value=payload["version"],
                )
        for key in ("show", "shot", "asset", "task", "user"):
            if key in payload:
                value = payload[key]
                data[key] = None if value is None else str(value)
        if "frame_range" in payload:
            data["frame_range"] = _parse_frame_range(payload["frame_range"])
        if "expected_frame_range" in payload:
            data["expected_frame_range"] = _parse_frame_range(
                payload["expected_frame_range"]
            )
        if "textures" in payload:
            data["textures"] = tuple(
                Path(str(entry)) for entry in _normalise_sequence(payload["textures"])
            )
        if "caches" in payload:
            data["caches"] = tuple(
                Path(str(entry)) for entry in _normalise_sequence(payload["caches"])
            )
        if "texture_color_spaces" in payload:
            mapping = {
                Path(str(key)): str(value)
                for key, value in dict(payload["texture_color_spaces"]).items()
            }
            data["texture_color_spaces"] = mapping
        if "render_layers" in payload:
            data["render_layers"] = _parse_render_items(
                payload["render_layers"], RenderLayer
            )
        if "takes" in payload:
            data["takes"] = _parse_render_items(payload["takes"], Take)

        return replace(self, **data)


def _parse_frame_range(value: Any) -> tuple[int, int] | None:
    if value is None:
        return None
    if isinstance(value, (list, tuple)) and len(value) == 2:
        try:
            start = int(value[0])
            end = int(value[1])
        except (TypeError, ValueError):
            return None
        return (start, end)
    if isinstance(value, str):
        parts = value.replace("..", "-").replace(":", "-").split("-")
        if len(parts) == 2:
            try:
                start = int(parts[0])
                end = int(parts[1])
            except ValueError:
                return None
            return (start, end)
    return None


def _parse_render_items(
    value: Any, item_type: type[RenderLayer] | type[Take]
) -> tuple[Any, ...]:
    items: list[Any] = []
    for entry in _normalise_sequence(value):
        if isinstance(entry, Mapping):
            name = entry.get("name")
            if not isinstance(name, str):
                continue
            renderable = bool(entry.get("renderable", True))
            items.append(item_type(name=name, renderable=renderable))
        elif isinstance(entry, str):
            items.append(item_type(name=entry, renderable=True))
    return tuple(items)


def _default_scene_path() -> Path:
    candidate = os.environ.get("SCENE_FILE")
    if candidate:
        return Path(candidate)
    return Path.cwd() / "scene.c4d"


def _load_context_payload_from_env() -> Mapping[str, Any] | None:
    payload_path = os.environ.get("C4D_SCENE_STATE")
    if not payload_path:
        return None
    try:
        data = json.loads(Path(payload_path).read_text())
    except FileNotFoundError:
        log.warning(
            "cinema4d_scene_validator.context_state_missing",
            path=payload_path,
        )
        return None
    except json.JSONDecodeError as exc:
        log.warning(
            "cinema4d_scene_validator.context_state_invalid",
            path=payload_path,
            error=str(exc),
        )
        return None
    if not isinstance(data, Mapping):
        log.warning(
            "cinema4d_scene_validator.context_state_type",
            path=payload_path,
        )
        return None
    return data


def collect_scene_context(module: object | None = None) -> SceneContext:
    """Return a :class:`SceneContext` constructed from the environment."""

    del module  # unused but kept for API symmetry with future integrations

    show = os.environ.get("SHOW")
    shot = os.environ.get("SHOT")
    if not show or not shot:
        raise RuntimeError("SHOW and SHOT environment variables must be set")

    asset = os.environ.get("ASSET")
    task = os.environ.get("TASK")
    user = os.environ.get("USER") or os.environ.get("USERNAME")
    version_env = os.environ.get("SCENE_VERSION")
    try:
        version = int(version_env) if version_env is not None else 1
    except ValueError:
        log.warning("cinema4d_scene_validator.invalid_env_version", value=version_env)
        version = 1

    expected_range = _parse_frame_range(os.environ.get("EXPECTED_FRAME_RANGE"))

    context = SceneContext(
        show=show,
        shot=shot,
        scene_path=_default_scene_path(),
        version=version,
        asset=asset,
        task=task,
        user=user,
        expected_frame_range=expected_range,
    )

    payload = _load_context_payload_from_env()
    if payload:
        context = context.with_updates(payload)

    return context


@dataclass(frozen=True)
class ValidationIssue:
    """Describe a validation issue detected for the scene."""

    validator: str
    message: str
    severity: str = "ERROR"


@dataclass(frozen=True)
class ValidationReport:
    """Report aggregating validator outcomes."""

    issues: tuple[ValidationIssue, ...]

    @property
    def is_valid(self) -> bool:
        return not self.issues


class SceneValidator:
    """Base class for scene validators."""

    name: str = ""

    def validate(
        self, context: SceneContext, options: ValidatorOptions
    ) -> Iterable[ValidationIssue]:
        raise NotImplementedError


class ValidatorRegistry:
    """Manage the available validator implementations."""

    def __init__(self) -> None:
        self._validators: dict[str, type[SceneValidator]] = {}

    def register(self, validator: type[SceneValidator]) -> None:
        if not validator.name:
            raise ValueError("Validator classes must define a non-empty name")
        self._validators[validator.name] = validator

    def get(self, name: str) -> type[SceneValidator] | None:
        return self._validators.get(name)

    def create(self, name: str) -> SceneValidator | None:
        validator_cls = self.get(name)
        if validator_cls is None:
            return None
        return validator_cls()

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._validators))


REGISTRY = ValidatorRegistry()


def validator(name: str) -> Callable[[type[SceneValidator]], type[SceneValidator]]:
    """Decorator registering a :class:`SceneValidator` implementation."""

    def _decorator(cls: type[SceneValidator]) -> type[SceneValidator]:
        cls.name = name
        REGISTRY.register(cls)
        return cls

    return _decorator


@validator("missing_assets")
class MissingAssetsValidator(SceneValidator):
    """Check that all textures and caches referenced by the scene exist."""

    def validate(
        self, context: SceneContext, options: ValidatorOptions
    ) -> Iterable[ValidationIssue]:
        del options
        for path in context.textures:
            if not path.exists():
                yield ValidationIssue(self.name, f"Missing texture: {path}")
        for path in context.caches:
            if not path.exists():
                yield ValidationIssue(self.name, f"Missing cache: {path}")


@validator("naming_convention")
class NamingConventionValidator(SceneValidator):
    """Ensure the scene name respects the configured naming pattern."""

    def validate(
        self, context: SceneContext, options: ValidatorOptions
    ) -> Iterable[ValidationIssue]:
        pattern = options.get("pattern", r"^[A-Za-z0-9_]+$")
        if not isinstance(pattern, str) or not pattern:
            pattern = r"^[A-Za-z0-9_]+$"
        compiled = re.compile(pattern)
        scene_name = context.scene_path.stem
        if not compiled.match(scene_name):
            message = (
                "Scene name does not match required pattern "
                f"'{pattern}': {scene_name}"
            )
            yield ValidationIssue(self.name, message)


@validator("texture_color_space")
class TextureColorSpaceValidator(SceneValidator):
    """Reject textures flagged as being in a non-linear colour space."""

    def validate(
        self, context: SceneContext, options: ValidatorOptions
    ) -> Iterable[ValidationIssue]:
        allowed = options.get("linear_spaces", {"linear", "acescg", "scene-linear"})
        if not isinstance(allowed, Iterable):
            allowed = {"linear", "acescg", "scene-linear"}
        allowed_set = {str(entry).lower() for entry in allowed}

        for path, color_space in context.texture_color_spaces.items():
            lowered = color_space.lower()
            if lowered and lowered not in allowed_set:
                message = (
                    f"Texture '{path}' uses non-linear colour space '{color_space}'"
                )
                yield ValidationIssue(self.name, message)


@validator("frame_range")
class FrameRangeValidator(SceneValidator):
    """Validate that the current frame range matches the expected range."""

    def validate(
        self, context: SceneContext, options: ValidatorOptions
    ) -> Iterable[ValidationIssue]:
        expected = context.expected_frame_range
        override = options.get("expected")
        override_range = _parse_frame_range(override)
        if override_range is not None:
            expected = override_range

        if expected is None or context.frame_range is None:
            return

        if tuple(context.frame_range) != tuple(expected):
            message = (
                f"Frame range mismatch: expected {expected}, got {context.frame_range}"
            )
            yield ValidationIssue(self.name, message)


@validator("renderable_items")
class RenderableItemsValidator(SceneValidator):
    """Ensure all configured render layers and takes are marked renderable."""

    def validate(
        self, context: SceneContext, options: ValidatorOptions
    ) -> Iterable[ValidationIssue]:
        ignore_layers = {
            str(name) for name in _normalise_sequence(options.get("ignore_layers"))
        }
        ignore_takes = {
            str(name) for name in _normalise_sequence(options.get("ignore_takes"))
        }

        for layer in context.render_layers:
            if not layer.renderable and layer.name not in ignore_layers:
                yield ValidationIssue(
                    self.name, f"Render layer '{layer.name}' is disabled"
                )

        for take in context.takes:
            if not take.renderable and take.name not in ignore_takes:
                yield ValidationIssue(
                    self.name, f"Take '{take.name}' is not renderable"
                )


@dataclass(frozen=True)
class ExportSummary:
    """Describe the outcome of an individual export step."""

    name: str
    outputs: tuple[Path, ...]


@dataclass(frozen=True)
class PipelineResult:
    """Aggregate result produced by :class:`ScenePublishPipeline`."""

    context: SceneContext
    report: ValidationReport
    exports: tuple[ExportSummary, ...]
    metadata_path: Path | None
    log_file: Path | None
    version: int

    @property
    def success(self) -> bool:
        return self.report.is_valid


@dataclass
class PublishActions:
    """Collection of callables executed once validation succeeds."""

    export_geometry: Callable[[SceneContext, Mapping[str, Any]], Sequence[Path]]
    export_redshift_proxies: Callable[[SceneContext, Mapping[str, Any]], Sequence[Path]]
    write_metadata: Callable[[SceneContext, Mapping[str, Any]], Path]
    update_render_paths: Callable[[SceneContext, Mapping[str, Any]], None]
    register_publish: Callable[[SceneContext, Mapping[str, Any]], None]


def _default_geometry_export(
    context: SceneContext, options: Mapping[str, Any]
) -> Sequence[Path]:
    format_hint = str(options.get("format", "alembic")).lower()
    extension = ".usd" if format_hint in {"usd", "usdc"} else ".abc"
    output_dir = Path(options.get("output_dir", context.scene_path.parent / "exports"))
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{context.scene_path.stem}_geo{extension}"
    output_path.write_text("exported geometry")
    log.info(
        "cinema4d_scene_validator.geometry_exported",
        output=str(output_path),
        format=format_hint,
    )
    return (output_path,)


def _default_proxy_export(
    context: SceneContext, options: Mapping[str, Any]
) -> Sequence[Path]:
    output_dir = Path(options.get("output_dir", context.scene_path.parent / "exports"))
    output_dir.mkdir(parents=True, exist_ok=True)
    proxy_path = output_dir / f"{context.scene_path.stem}_proxy.rs"
    proxy_path.write_text("redshift proxy")
    log.info(
        "cinema4d_scene_validator.proxy_exported",
        output=str(proxy_path),
    )
    return (proxy_path,)


def _default_metadata_writer(context: SceneContext, options: Mapping[str, Any]) -> Path:
    output_dir = Path(options.get("output_dir", context.scene_path.parent / "exports"))
    output_dir.mkdir(parents=True, exist_ok=True)
    metadata_path = output_dir / f"{context.scene_path.stem}_metadata.json"
    payload = {
        "show": context.show,
        "shot": context.shot,
        "asset": context.asset,
        "task": context.task,
        "version": options.get("version", context.version),
        "user": context.user,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    metadata_path.write_text(json.dumps(payload, indent=2, sort_keys=True))
    log.info(
        "cinema4d_scene_validator.metadata_written",
        output=str(metadata_path),
    )
    return metadata_path


def _default_render_path_update(
    context: SceneContext, options: Mapping[str, Any]
) -> None:
    del options
    log.info(
        "cinema4d_scene_validator.render_paths_updated",
        scene=str(context.scene_path),
        version=context.version,
    )


def _default_publish_registration(
    context: SceneContext, options: Mapping[str, Any]
) -> None:
    endpoint = options.get("endpoint")
    log.info(
        "cinema4d_scene_validator.publish_registered",
        show=context.show,
        shot=context.shot,
        asset=context.asset,
        task=context.task,
        endpoint=endpoint,
    )


DEFAULT_ACTIONS = PublishActions(
    export_geometry=_default_geometry_export,
    export_redshift_proxies=_default_proxy_export,
    write_metadata=_default_metadata_writer,
    update_render_paths=_default_render_path_update,
    register_publish=_default_publish_registration,
)


def _normalise_config_entries(entries: Any) -> Iterator[tuple[str, dict[str, Any]]]:
    if not isinstance(entries, Iterable) or isinstance(entries, (str, bytes)):
        return iter(())
    normalised: list[tuple[str, dict[str, Any]]] = []
    for entry in entries:
        if isinstance(entry, str):
            normalised.append((entry, {}))
            continue
        if isinstance(entry, Mapping):
            name = entry.get("name")
            if not isinstance(name, str):
                continue
            options = {key: value for key, value in entry.items() if key != "name"}
            normalised.append((name, dict(options)))
    return iter(normalised)


def _load_json(path: Path) -> Mapping[str, Any] | None:
    try:
        payload = json.loads(path.read_text())
    except FileNotFoundError:
        return None
    except json.JSONDecodeError as exc:
        log.warning(
            "cinema4d_scene_validator.config_invalid",
            path=str(path),
            error=str(exc),
        )
        return None
    if not isinstance(payload, Mapping):
        log.warning(
            "cinema4d_scene_validator.config_type",
            path=str(path),
        )
        return None
    return payload


def load_show_config(show: str, *, root: Path | None = None) -> Mapping[str, Any]:
    """Return the JSON configuration for ``show`` when available."""

    override = os.environ.get("ONEPIECE_C4D_PUBLISH_CONFIG")
    if override:
        payload = _load_json(Path(override))
        if payload is not None:
            return payload

    if root is None:
        root_env = os.environ.get("ONEPIECE_C4D_CONFIG_ROOT")
        root = Path(root_env) if root_env else Path.home() / ".config/onepiece/cinema4d"

    path = Path(root) / f"{show.lower()}.json"
    payload = _load_json(path)
    if payload is not None:
        return payload

    return {
        "validators": [
            "missing_assets",
            "naming_convention",
            "texture_color_space",
            "frame_range",
            "renderable_items",
        ],
        "exports": [
            {"name": "geometry", "format": "alembic"},
            {"name": "redshift_proxies"},
            {"name": "metadata"},
            {"name": "update_render_paths"},
            {"name": "register_publish"},
        ],
    }


def _write_pipeline_log(
    context: SceneContext,
    report: ValidationReport,
    exports: Sequence[ExportSummary],
    metadata_path: Path | None,
    *,
    log_dir: Path | None,
) -> Path | None:
    if log_dir is None:
        log_dir_env = os.environ.get("PIPELINE_LOG_DIR") or os.environ.get(
            "ONEPIECE_PIPELINE_LOG_DIR"
        )
        log_dir = Path(log_dir_env) if log_dir_env else None

    if log_dir is None:
        return None

    log_dir.mkdir(parents=True, exist_ok=True)
    stem = "_".join(
        filter(
            None, [context.show, context.shot, context.task or "publish", "pipeline"]
        )
    )
    path = log_dir / f"{stem}.log"

    lines = [
        f"Scene Validator Report for {context.show}/{context.shot}",
        f"  Scene: {context.scene_path}",
        f"  Version: {context.version}",
        "  Result: " + ("SUCCESS" if report.is_valid else "FAILED"),
    ]
    if report.issues:
        lines.append("  Issues:")
        for issue in report.issues:
            lines.append(f"    - [{issue.severity}] {issue.validator}: {issue.message}")
    if exports:
        lines.append("  Exports:")
        for export in exports:
            outputs = ", ".join(str(path) for path in export.outputs)
            lines.append(f"    - {export.name}: {outputs}")
    if metadata_path is not None:
        lines.append(f"  Metadata: {metadata_path}")

    path.write_text("\n".join(lines) + "\n")
    return path


class ScenePublishPipeline:
    """Execute validation and publishing actions for the current scene."""

    def __init__(
        self,
        *,
        context_provider: Callable[[], SceneContext],
        registry: ValidatorRegistry | None = None,
        config_loader: Callable[[str], Mapping[str, Any]] | None = None,
        actions: PublishActions | None = None,
    ) -> None:
        self._context_provider = context_provider
        self._registry = registry or REGISTRY
        self._config_loader = config_loader or (lambda show: load_show_config(show))
        self._actions = actions or DEFAULT_ACTIONS

    def _iter_validators(
        self, config: Mapping[str, Any]
    ) -> Iterator[tuple[str, dict[str, Any]]]:
        yield from _normalise_config_entries(config.get("validators", ()))

    def _iter_exports(
        self, config: Mapping[str, Any]
    ) -> Iterator[tuple[str, dict[str, Any]]]:
        yield from _normalise_config_entries(config.get("exports", ()))

    def _run_validators(
        self, context: SceneContext, config: Mapping[str, Any]
    ) -> ValidationReport:
        issues: list[ValidationIssue] = []
        for name, options in self._iter_validators(config):
            validator = self._registry.create(name)
            if validator is None:
                log.warning(
                    "cinema4d_scene_validator.unknown_validator",
                    validator=name,
                )
                continue
            try:
                issues.extend(validator.validate(context, options))
            except Exception as exc:  # pragma: no cover - defensive guard
                log.error(
                    "cinema4d_scene_validator.validator_error",
                    validator=name,
                    error=str(exc),
                )
                issues.append(
                    ValidationIssue(
                        name,
                        f"Validator '{name}' failed: {exc}",
                        severity="ERROR",
                    )
                )
        return ValidationReport(tuple(issues))

    def _run_exports(
        self,
        context: SceneContext,
        config: Mapping[str, Any],
        *,
        version: int,
    ) -> tuple[tuple[ExportSummary, ...], Path | None]:
        summaries: list[ExportSummary] = []
        metadata_path: Path | None = None
        for name, options in self._iter_exports(config):
            lower = name.lower()
            if lower in {"geometry", "alembic", "usd"}:
                export_options = dict(options)
                export_options.setdefault("format", lower)
                outputs = self._actions.export_geometry(context, export_options)
                summaries.append(
                    ExportSummary(
                        name="geometry", outputs=tuple(Path(p) for p in outputs)
                    )
                )
            elif lower in {"redshift", "redshift_proxies", "redshift_proxy"}:
                outputs = self._actions.export_redshift_proxies(context, options)
                summaries.append(
                    ExportSummary(
                        name="redshift_proxies",
                        outputs=tuple(Path(p) for p in outputs),
                    )
                )
            elif lower == "metadata":
                export_options = dict(options)
                export_options.setdefault("version", version)
                metadata_path = self._actions.write_metadata(context, export_options)
            elif lower in {"update_render_paths", "render_paths"}:
                self._actions.update_render_paths(context, options)
            elif lower in {"register_publish", "asset_db"}:
                self._actions.register_publish(context, options)
            else:
                log.warning(
                    "cinema4d_scene_validator.unknown_export",
                    export=name,
                )
        return tuple(summaries), metadata_path

    def run(self) -> PipelineResult:
        context = self._context_provider()
        config = self._config_loader(context.show)
        report = self._run_validators(context, config)

        version = context.version + 1
        exports: tuple[ExportSummary, ...] = ()
        metadata_path: Path | None = None
        if report.is_valid:
            exports, metadata_path = self._run_exports(context, config, version=version)
        else:
            log.info(
                "cinema4d_scene_validator.validation_failed",
                issues=[issue.message for issue in report.issues],
            )

        log_dir = config.get("log_directory")
        log_path = _write_pipeline_log(
            context,
            report,
            exports,
            metadata_path,
            log_dir=Path(log_dir) if isinstance(log_dir, str) else None,
        )

        return PipelineResult(
            context=context,
            report=report,
            exports=exports,
            metadata_path=metadata_path,
            log_file=log_path,
            version=version,
        )


def build_pipeline(module: object | None = None) -> ScenePublishPipeline:
    """Return a pipeline configured with the default runtime dependencies."""

    return ScenePublishPipeline(
        context_provider=lambda: collect_scene_context(module),
    )


__all__ = [
    "PipelineResult",
    "PublishActions",
    "RenderLayer",
    "SceneContext",
    "ScenePublishPipeline",
    "Take",
    "ValidationIssue",
    "ValidationReport",
    "build_pipeline",
    "collect_scene_context",
    "load_show_config",
    "REGISTRY",
]
