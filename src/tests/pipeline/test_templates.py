from __future__ import annotations

import pytest

from libraries.pipeline.templates import get_pipeline_template, list_pipeline_templates


def test_list_pipeline_templates_returns_entries() -> None:
    templates = list_pipeline_templates()

    assert templates
    assert all(template.name for template in templates)


def test_get_pipeline_template_is_case_insensitive() -> None:
    template = list_pipeline_templates()[0]

    resolved = get_pipeline_template(template.name.upper())

    assert resolved.name == template.name


def test_get_pipeline_template_unknown_name_raises() -> None:
    with pytest.raises(KeyError):
        get_pipeline_template("missing.template")
