import pytest

from libraries.automation.review.dailies import _extract_duration


def test_extract_duration_handles_zero_frame_count() -> None:
    attributes: dict[str, object] = {
        "sg_uploaded_movie_frame_count": 0,
        "sg_uploaded_movie_frame_rate": 24,
    }

    assert _extract_duration(attributes) == pytest.approx(0.0)
