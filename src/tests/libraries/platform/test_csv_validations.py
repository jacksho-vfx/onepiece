from pathlib import Path

import pytest

from libraries.platform.validations.csv_validations import validate_shots_csv


def _write_csv(tmp_path: Path, name: str, content: str) -> Path:
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path


def test_validate_shots_csv_accepts_bom_header(tmp_path: Path) -> None:
    csv_path = _write_csv(
        tmp_path,
        "shots_bom.csv",
        "\ufeffShot Code,Other\nE01_S01_SH001,foo\nE01_S01_SH002,bar\n",
    )

    result = validate_shots_csv(csv_path)

    assert result == ["E01_S01_SH001", "E01_S01_SH002"]


def test_validate_shots_csv_accepts_padded_header(tmp_path: Path) -> None:
    csv_path = _write_csv(
        tmp_path,
        "shots_padded.csv",
        "  shot-column  ,Other\nE02-S03-SH010,baz\n",
    )

    result = validate_shots_csv(csv_path)

    assert result == ["E02-S03-SH010"]


def test_validate_shots_csv_rejects_incorrect_digit_counts(tmp_path: Path) -> None:
    csv_path = _write_csv(
        tmp_path,
        "shots_invalid_digits.csv",
        "Shot,Other\nE1_S01_SH001,foo\nE01_S1_SH001,bar\nE01_S01_SH01,baz\n",
    )

    with pytest.raises(ValueError) as excinfo:
        validate_shots_csv(csv_path)

    assert "Invalid shot code format" in str(excinfo.value)
