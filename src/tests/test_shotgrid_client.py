import logging
from typing import Callable, cast

import pytest

from src.libraries.shotgrid.client import (
    EntityStore,
    HierarchyTemplate,
    RetryPolicy,
    ShotgridClient,
    ShotgridOperationError,
    TemplateNode,
    TEntity,
)


class FlakyStore(EntityStore):
    """Entity store that fails the first ``add`` invocation."""

    def __init__(self) -> None:
        super().__init__()
        self.attempts = 0

    def add(self, entity_type: str, entity: TEntity) -> TEntity:
        self.attempts += 1
        if self.attempts < 2:
            raise RuntimeError("transient failure")
        return cast(TEntity, super().add(entity_type, entity))


def test_bulk_create_entities_batches(monkeypatch: pytest.MonkeyPatch) -> None:
    client = ShotgridClient(batch_size=2)

    batch_sizes: list[int] = []
    original_execute = client._execute_with_retry

    def recorder(
        func: Callable[..., object], *args: object, **kwargs: object
    ) -> object:
        if args:
            batch_sizes.append(len(args[0]))  # type: ignore[arg-type]
        return original_execute(func, *args, **kwargs)

    monkeypatch.setattr(client, "_execute_with_retry", recorder)

    payloads = [{"code": f"Asset_{index}"} for index in range(5)]

    created = client.bulk_create_entities("Asset", payloads)

    assert len(created) == 5
    assert batch_sizes == [2, 2, 1]


def test_bulk_update_entities_batches(monkeypatch: pytest.MonkeyPatch) -> None:
    client = ShotgridClient(batch_size=2)
    created = client.bulk_create_entities(
        "Asset", [{"code": f"Asset_{index}"} for index in range(4)]
    )

    batch_sizes: list[int] = []
    original_execute = client._execute_with_retry

    def recorder(
        func: Callable[..., object], *args: object, **kwargs: object
    ) -> object:
        if args:
            batch_sizes.append(len(args[0]))  # type: ignore[arg-type]
        return original_execute(func, *args, **kwargs)

    monkeypatch.setattr(client, "_execute_with_retry", recorder)

    updates = [
        {"id": entity["id"], "description": f"Updated {index}"}
        for index, entity in enumerate(created)
    ]

    updated = client.bulk_update_entities("Asset", updates)

    assert [entry["description"] for entry in updated] == [
        "Updated 0",
        "Updated 1",
        "Updated 2",
        "Updated 3",
    ]
    assert batch_sizes == [2, 2]


def test_bulk_delete_entities_batches(monkeypatch: pytest.MonkeyPatch) -> None:
    client = ShotgridClient(batch_size=2)
    created = client.bulk_create_entities(
        "Asset", [{"code": f"Asset_{index}"} for index in range(4)]
    )

    batch_sizes: list[int] = []
    original_execute = client._execute_with_retry

    def recorder(
        func: Callable[..., object], *args: object, **kwargs: object
    ) -> object:
        if args:
            batch_sizes.append(len(args[0]))  # type: ignore[arg-type]
        return original_execute(func, *args, **kwargs)

    monkeypatch.setattr(client, "_execute_with_retry", recorder)

    client.bulk_delete_entities("Asset", [entity["id"] for entity in created])

    assert batch_sizes == [2, 2]
    assert client._store.list("Asset") == []


def test_bulk_create_update_delete_entities() -> None:
    client = ShotgridClient(sleep=lambda _: None)

    created = client.bulk_create_entities(
        "Shot",
        [{"code": "shot_001"}, {"code": "shot_002"}],
    )

    assert [entity["code"] for entity in created] == ["shot_001", "shot_002"]

    updated = client.bulk_update_entities(
        "Shot",
        [{"id": created[0]["id"], "code": "shot_001_v2"}],
    )

    assert updated[0]["code"] == "shot_001_v2"

    client.bulk_delete_entities("Shot", [created[1]["id"]])

    with pytest.raises(ShotgridOperationError):
        client.bulk_update_entities(
            "Shot", [{"id": created[1]["id"], "code": "missing"}]
        )


def test_bulk_create_retries_transient_failures() -> None:
    store = FlakyStore()
    policy = RetryPolicy(max_attempts=3, base_delay=0, jitter=0)
    client = ShotgridClient(store=store, retry_policy=policy, sleep=lambda _: None)

    created = client.bulk_create_entities("Scene", [{"code": "sc01"}])

    assert created[0]["code"] == "sc01"
    assert store.attempts == 2


def test_execute_with_retry_backoff(caplog: pytest.LogCaptureFixture) -> None:
    delays: list[float] = []

    def capture_sleep(duration: float) -> None:
        delays.append(duration)

    client = ShotgridClient(
        sleep=capture_sleep,
        retry_policy=RetryPolicy(
            max_attempts=4, base_delay=0.1, max_delay=0.2, jitter=0.0
        ),
    )

    attempts = {"count": 0}

    def flaky() -> str:
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise RuntimeError("boom")
        return "ok"

    with caplog.at_level(logging.WARNING):
        result = client._execute_with_retry(flaky)

    assert result == "ok"
    assert delays == [0.1, 0.2]
    assert any("shotgrid.retry_pending" in record.message for record in caplog.records)


def test_execute_with_retry_raises_actionable_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = ShotgridClient(
        sleep=lambda _duration: None,
        retry_policy=RetryPolicy(
            max_attempts=2, base_delay=0.01, max_delay=0.01, jitter=0.0
        ),
    )

    def fail() -> None:
        raise RuntimeError("nope")

    with caplog.at_level(logging.ERROR):
        with pytest.raises(ShotgridOperationError) as excinfo:
            client._execute_with_retry(fail)

    message = str(excinfo.value)
    assert "Operation fail failed after 2 attempts" in message
    assert "RuntimeError('nope')" in message
    assert any(
        "shotgrid.retry_exhausted" in record.message for record in caplog.records
    )


def test_apply_hierarchy_template_supports_contextual_values() -> None:
    client = ShotgridClient(batch_size=3)

    template = HierarchyTemplate(
        name="EpisodeStructure",
        roots=(
            TemplateNode(
                entity_type="Episode",
                attributes={
                    "code": lambda ctx: f"EP{ctx['episode']:02d}",
                    "description": "Episode {episode}",
                },
                context_updates={
                    "episode_code": lambda ctx: ctx["entity"]["code"],
                },
                children=(
                    TemplateNode(
                        entity_type="Sequence",
                        attributes={
                            "code": "{episode_code}_SQ{sequence:02d}",
                            "name": lambda ctx: f"Sequence {ctx['sequence']}",
                        },
                        context_updates={
                            "sequence_code": lambda ctx: ctx["entity"]["code"],
                        },
                        children=(
                            TemplateNode(
                                entity_type="Shot",
                                attributes={
                                    "code": "{sequence_code}_SH{shot:02d}",
                                    "description": lambda ctx: f"Shot {ctx['shot']}",
                                },
                            ),
                        ),
                    ),
                ),
            ),
        ),
    )

    result = client.apply_hierarchy_template(
        "MyProject",
        template,
        context={"episode": 1, "sequence": 5, "shot": 12},
    )

    assert {entity["code"] for entity in result["Episode"]} == {"EP01"}
    assert result["Episode"][0]["project_id"] == 1
    assert result["Sequence"][0]["code"] == "EP01_SQ05"
    assert result["Shot"][0]["code"] == "EP01_SQ05_SH12"
    assert result["Shot"][0]["description"] == "Shot 12"
