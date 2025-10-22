"""Tests for the Perona database schema and migration helpers."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from apps.perona.db import (
    MIGRATIONS,
    apply_migrations,
    get_applied_migrations,
    latest_migration_id,
)


def _table_exists(connection: sqlite3.Connection, name: str) -> bool:
    cursor = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    )
    return cursor.fetchone() is not None


def test_apply_migrations_creates_expected_tables(tmp_path: Path) -> None:
    database = tmp_path / "perona.db"
    connection = sqlite3.connect(database)
    try:
        applied = apply_migrations(connection)
        assert applied == [migration.identifier for migration in MIGRATIONS]

        assert _table_exists(connection, "perona_render_metrics")
        assert _table_exists(connection, "perona_risk_indicators")
        assert _table_exists(connection, "perona_shot_lifecycle_stages")
        assert _table_exists(connection, "perona_pnl_snapshots")
        assert _table_exists(connection, "perona_pnl_contributions")

        applied_migrations = get_applied_migrations(connection)
        assert applied_migrations == applied
    finally:
        connection.close()


def test_apply_migrations_is_idempotent(tmp_path: Path) -> None:
    database = tmp_path / "perona_idempotent.db"
    connection = sqlite3.connect(database)
    try:
        first_run = apply_migrations(connection)
        second_run = apply_migrations(connection)
        assert first_run
        assert second_run == []
        assert get_applied_migrations(connection) == first_run
    finally:
        connection.close()


def test_latest_migration_id_tracks_tail() -> None:
    assert latest_migration_id(MIGRATIONS) == MIGRATIONS[-1].identifier

