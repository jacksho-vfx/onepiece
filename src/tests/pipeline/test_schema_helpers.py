from pathlib import Path

import pytest

from apps.onepiece.pipeline.clients import PipelineClientError
from apps.onepiece.pipeline.io import _parse_pipeline_parameters
from apps.onepiece.pipeline.schema import (
    PipelineParameterSchema,
    PipelineSchemaError,
    _example_value_for_parameter,
    load_pipeline_manifest,
)


def test_manifest_loader_supports_toml(tmp_path: Path) -> None:
    manifest = tmp_path / "pipeline.toml"
    manifest.write_text("name = 'demo'\nversion = '1.0'\n", encoding="utf-8")

    payload = load_pipeline_manifest(manifest)

    assert payload["name"] == "demo"
    assert payload["version"] == "1.0"


def test_manifest_loader_reports_missing_file(tmp_path: Path) -> None:
    missing = tmp_path / "absent.yaml"
    with pytest.raises(PipelineSchemaError):
        load_pipeline_manifest(missing)


def test_parameter_schema_validates_and_templates() -> None:
    schema = PipelineParameterSchema.from_payload(
        {
            "mode": {"type": "string", "choices": ["fast", "slow"], "default": "fast"},
            "threshold": {"type": "number", "required": True},
        },
        source="unit test",
    )

    template = schema.example_template()
    assert template["mode"]["example"] == "fast"

    threshold_definition = schema.parameters["threshold"]
    assert _example_value_for_parameter(threshold_definition, name="threshold") == 1.0

    parsed = _parse_pipeline_parameters(
        ["threshold=0.5"],
        base={"mode": "slow"},
        schema=schema,
        interactive=False,
    )

    assert parsed == {"mode": "slow", "threshold": 0.5}

    with pytest.raises(PipelineClientError):
        _parse_pipeline_parameters(["unknown=1"], schema=schema, interactive=False)

    with pytest.raises(PipelineClientError):
        _parse_pipeline_parameters(None, schema=schema, interactive=False)
