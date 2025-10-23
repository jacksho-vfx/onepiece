from unittest.mock import MagicMock

from libraries.integrations.shotgrid.show_setup import setup_single_shot


def test_setup_single_shot_forwards_template_to_client() -> None:
    client = MagicMock()
    client.get_or_create_project.return_value = {"id": 42}

    result = setup_single_shot(
        "My Project", "E01_S01_SH010", template="cool-template", client=client
    )

    client.get_or_create_project.assert_called_once_with(
        "My Project", template="cool-template"
    )
    assert result["project"] == {"id": 42}
