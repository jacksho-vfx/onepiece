from libraries.automation.reconcile.comparator import compare_datasets


def test_compare_datasets_normalises_shots_filter() -> None:
    shotgrid = [
        {
            "shot": "ep101_sc01_0010",
            "version": "v001",
        }
    ]
    filesystem: list[dict[str, str]] = []

    mismatches = compare_datasets(
        shotgrid,
        filesystem,
        shots=["EP101_SC01_0010"],
    )

    assert any(item["type"] == "missing_in_fs" for item in mismatches)


def test_compare_datasets_normalises_numeric_versions() -> None:
    shotgrid = [
        {
            "shot": "ep201_sc01_0010",
            "version": "v003",
        }
    ]
    filesystem = [
        {
            "shot": "ep201_sc01_0010",
            "version": "003",
        }
    ]

    mismatches = compare_datasets(shotgrid, filesystem)

    assert mismatches == []
