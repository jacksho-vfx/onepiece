from collections.abc import Generator, Iterable

import pytest

from apps.trafalgar.app import pipeline_cancel
from apps.trafalgar.pipeline import set_pipeline_orchestrator


@pytest.fixture
def restore_orchestrator() -> Generator[None, None, None]:
    try:
        yield
    finally:
        set_pipeline_orchestrator(None)


def test_pipeline_cancel_invokes_orchestrator(
    capsys: pytest.CaptureFixture[str], restore_orchestrator: None
) -> None:
    calls: dict[str, object] = {}

    class DummyOrchestrator:
        def cancel_runs(
            self, run_ids: Iterable[str], *, force: bool = False
        ) -> dict[str, bool]:
            calls["run_ids"] = list(run_ids)
            calls["force"] = force
            return {run_id: True for run_id in run_ids}

    orchestrator = DummyOrchestrator()
    set_pipeline_orchestrator(orchestrator)

    pipeline_cancel(["run-1", "run-2"], force=True)

    assert calls == {"run_ids": ["run-1", "run-2"], "force": True}
    output = capsys.readouterr().out.strip().splitlines()
    assert output == [
        "Cancelled run 'run-1'.",
        "Cancelled run 'run-2'.",
    ]


def test_pipeline_cancel_reports_failures(
    capsys: pytest.CaptureFixture[str], restore_orchestrator: None
) -> None:
    class DummyOrchestrator:
        def cancel_runs(
            self, run_ids: Iterable[str], *, force: bool = False
        ) -> dict[str, bool]:
            return {run_id: False for run_id in run_ids}

    set_pipeline_orchestrator(DummyOrchestrator())

    with pytest.raises(SystemExit) as excinfo:
        pipeline_cancel(["missing"], force=False)

    assert excinfo.value.code == 1
    output = capsys.readouterr().out.strip().splitlines()
    assert output == ["Cancellation requested for run 'missing'."]
