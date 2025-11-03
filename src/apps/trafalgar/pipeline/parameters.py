"""Parameter schema utilities for Trafalgar pipelines."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

__all__ = [
    "_UNSET",
    "_PARAMETER_TYPE_ALIASES",
    "_coerce_string",
    "_coerce_integer",
    "_coerce_number",
    "_coerce_bool",
    "_PARAMETER_TYPE_COERCERS",
    "_normalise_parameter_type",
    "_coerce_parameter_value",
    "ParameterDefinition",
    "_parameter_definition_from_payload",
    "_parse_parameter_definitions",
]


_UNSET: Any = object()


_PARAMETER_TYPE_ALIASES: Mapping[str, str] = {
    "str": "string",
    "text": "string",
    "string": "string",
    "int": "integer",
    "integer": "integer",
    "bool": "boolean",
    "boolean": "boolean",
    "float": "number",
    "double": "number",
    "number": "number",
}


def _coerce_string(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _coerce_integer(value: Any) -> int:
    if isinstance(value, bool):
        msg = "boolean values are not valid integers"
        raise ValueError(msg)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            msg = "empty strings are not valid integers"
            raise ValueError(msg)
        try:
            return int(text)
        except ValueError as exc:
            raise ValueError(str(exc)) from exc
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(str(exc)) from exc


def _coerce_number(value: Any) -> float:
    if isinstance(value, bool):
        msg = "boolean values are not valid numbers"
        raise ValueError(msg)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            msg = "empty strings are not valid numbers"
            raise ValueError(msg)
        try:
            return float(text)
        except ValueError as exc:
            raise ValueError(str(exc)) from exc
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(str(exc)) from exc


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalised = value.strip().lower()
        if normalised in {"1", "true", "yes", "on"}:
            return True
        if normalised in {"0", "false", "no", "off"}:
            return False
    return bool(value)


_PARAMETER_TYPE_COERCERS: Mapping[str, Callable[[Any], Any]] = {
    "string": _coerce_string,
    "integer": _coerce_integer,
    "number": _coerce_number,
    "boolean": _coerce_bool,
}


def _normalise_parameter_type(raw: Any) -> str:
    if raw is None:
        msg = "parameter type cannot be None"
        raise ValueError(msg)
    text = str(raw).strip().lower()
    if not text:
        msg = "parameter type cannot be empty"
        raise ValueError(msg)
    canonical = _PARAMETER_TYPE_ALIASES.get(text, text)
    if canonical not in _PARAMETER_TYPE_COERCERS:
        msg = f"unsupported parameter type '{raw}'"
        raise ValueError(msg)
    return canonical


def _coerce_parameter_value(value: Any, *, type_name: str) -> Any:
    coercer = _PARAMETER_TYPE_COERCERS.get(type_name)
    if coercer is None:
        msg = f"unsupported parameter type '{type_name}'"
        raise ValueError(msg)
    return coercer(value)


@dataclass(frozen=True, slots=True)
class ParameterDefinition:
    """Schema describing a pipeline parameter."""

    default: Any = _UNSET
    required: bool = False
    description: str | None = None
    type: str | None = None
    choices: tuple[Any, ...] | None = None

    def __post_init__(self) -> None:  # pragma: no cover - dataclass hook
        object.__setattr__(self, "required", _coerce_bool(self.required))
        description = self.description
        if description is not None:
            text = str(description).strip()
            object.__setattr__(self, "description", text or None)
        type_name = self.type
        if type_name is not None:
            object.__setattr__(self, "type", _normalise_parameter_type(type_name))
        choices = self.choices
        if choices is not None:
            if isinstance(choices, tuple):
                normalised_choices = choices
            elif isinstance(choices, Sequence) and not isinstance(
                choices, (str, bytes, bytearray)
            ):
                normalised_choices = tuple(choices)
            else:
                msg = "parameter choices must be a sequence"
                raise TypeError(msg)
            if normalised_choices:
                object.__setattr__(self, "choices", normalised_choices)
            else:
                object.__setattr__(self, "choices", None)

    @property
    def has_default(self) -> bool:
        return self.default is not _UNSET

    @property
    def has_choices(self) -> bool:
        return bool(self.choices)

    def coerce(self, value: Any) -> Any:
        type_name = self.type
        coerced = value
        if type_name is not None:
            coerced = _coerce_parameter_value(value, type_name=type_name)
        choices = self.choices
        if choices:
            if coerced not in choices:
                options = ", ".join(map(repr, choices))
                msg = f"value must be one of: {options}"
                raise ValueError(msg)
        return coerced

    def serialise(self) -> Mapping[str, Any]:
        payload: dict[str, Any] = {"required": self.required}
        if self.has_default:
            payload["default"] = self.default
        if self.description is not None:
            payload["description"] = self.description
        if self.type is not None:
            payload["type"] = self.type
        if self.choices is not None:
            payload["choices"] = list(self.choices)
        return payload


def _parameter_definition_from_payload(
    value: Any, *, parameter: str, location: str
) -> ParameterDefinition:
    if isinstance(value, ParameterDefinition):
        return value
    if isinstance(value, Mapping):
        has_default = "default" in value
        default = value.get("default") if has_default else _UNSET
        required = _coerce_bool(value.get("required", False))
        description = value.get("description")
        type_name: str | None = None
        if "type" in value and value.get("type") is not None:
            try:
                type_name = _normalise_parameter_type(value.get("type"))
            except ValueError as exc:
                msg = f"{location} parameter '{parameter}' has invalid type: {exc}"
                raise ValueError(msg) from exc
        choices_value = value.get("choices")
        choices: tuple[Any, ...] | None = None
        if choices_value is not None:
            if isinstance(choices_value, Sequence) and not isinstance(
                choices_value, (str, bytes, bytearray)
            ):
                raw_choices = list(choices_value)
            else:
                msg = f"{location} parameter '{parameter}' choices must be a sequence"
                raise TypeError(msg)
            if type_name is not None:
                try:
                    coerced_choices = tuple(
                        _coerce_parameter_value(option, type_name=type_name)
                        for option in raw_choices
                    )
                except ValueError as exc:
                    msg = (
                        f"{location} parameter '{parameter}' choices contain an"
                        f" invalid value: {exc}"
                    )
                    raise ValueError(msg) from exc
                choices = coerced_choices
            else:
                choices = tuple(raw_choices)
        if has_default and type_name is not None and default is not _UNSET:
            try:
                default = _coerce_parameter_value(default, type_name=type_name)
            except ValueError as exc:
                msg = (
                    f"{location} parameter '{parameter}' default value is not a"
                    f" valid {type_name}: {exc}"
                )
                raise ValueError(msg) from exc
        if choices is not None and not choices:
            choices = None
        if choices is not None and has_default and default is not _UNSET:
            if default not in choices:
                options = ", ".join(map(repr, choices))
                msg = (
                    f"{location} parameter '{parameter}' default must be one of:"
                    f" {options}"
                )
                raise ValueError(msg)
        return ParameterDefinition(
            default=default if has_default else _UNSET,
            required=required,
            description=description,
            type=type_name,
            choices=choices,
        )
    return ParameterDefinition(default=value)


def _parse_parameter_definitions(
    raw: Mapping[str, Any] | None, *, location: str
) -> dict[str, ParameterDefinition]:
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        msg = f"{location} parameters must be a mapping"
        raise TypeError(msg)

    parameters: dict[str, ParameterDefinition] = {}
    for raw_name, raw_definition in raw.items():
        name = str(raw_name).strip()
        if not name:
            msg = f"{location} parameter names must be non-empty"
            raise ValueError(msg)
        parameters[name] = _parameter_definition_from_payload(
            raw_definition, parameter=name, location=location
        )
    return parameters
