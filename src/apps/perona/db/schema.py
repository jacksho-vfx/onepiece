"""Database schema and migration helpers for the Perona dashboard."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Iterable, Sequence

_MIGRATION_TABLE = "perona_schema_migrations"


@dataclass(frozen=True)
class Migration:
    """Represents a database migration step."""

    identifier: str
    description: str
    statements: tuple[str, ...]


MIGRATIONS: tuple[Migration, ...] = (
    Migration(
        identifier="0001_initial",
        description="Seed render telemetry, lifecycle, risk, and P&L tables.",
        statements=(
            """
            CREATE TABLE IF NOT EXISTS perona_render_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sequence TEXT NOT NULL,
                shot_id TEXT NOT NULL,
                captured_at TEXT NOT NULL,
                fps REAL NOT NULL,
                frame_time_ms REAL NOT NULL,
                error_count INTEGER NOT NULL,
                gpu_utilisation REAL NOT NULL,
                cache_health REAL NOT NULL,
                ingested_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_perona_render_metrics_shot_time
                ON perona_render_metrics (sequence, shot_id, captured_at)
            """,
            """
            CREATE TABLE IF NOT EXISTS perona_risk_indicators (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sequence TEXT NOT NULL,
                shot_id TEXT NOT NULL,
                risk_score REAL NOT NULL,
                render_time_ms REAL NOT NULL,
                error_rate REAL NOT NULL,
                cache_stability REAL NOT NULL,
                drivers TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_perona_risk_indicators_shot
                ON perona_risk_indicators (sequence, shot_id)
            """,
            """
            CREATE TABLE IF NOT EXISTS perona_shot_lifecycle_stages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sequence TEXT NOT NULL,
                shot_id TEXT NOT NULL,
                stage TEXT NOT NULL,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                metrics_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_perona_shot_lifecycle_shot_stage
                ON perona_shot_lifecycle_stages (sequence, shot_id, stage)
            """,
            """
            CREATE TABLE IF NOT EXISTS perona_pnl_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                captured_at TEXT NOT NULL,
                baseline_cost REAL NOT NULL,
                current_cost REAL NOT NULL,
                delta_cost REAL NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS perona_pnl_contributions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_id INTEGER NOT NULL,
                factor TEXT NOT NULL,
                delta_cost REAL NOT NULL,
                percentage_points REAL NOT NULL,
                narrative TEXT NOT NULL,
                FOREIGN KEY(snapshot_id) REFERENCES perona_pnl_snapshots(id) ON DELETE CASCADE
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_perona_pnl_contributions_snapshot
                ON perona_pnl_contributions (snapshot_id)
            """,
        ),
    ),
)


def _ensure_migrations_table(connection: sqlite3.Connection) -> None:
    """Create the schema migrations bookkeeping table when missing."""

    connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_MIGRATION_TABLE} (
            identifier TEXT PRIMARY KEY,
            description TEXT NOT NULL,
            applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


def get_applied_migrations(connection: sqlite3.Connection) -> list[str]:
    """Return the migration identifiers already applied to *connection*."""

    _ensure_migrations_table(connection)
    cursor = connection.execute(
        f"SELECT identifier FROM {_MIGRATION_TABLE} ORDER BY applied_at"
    )
    return [row[0] for row in cursor.fetchall()]


def apply_migrations(
    connection: sqlite3.Connection,
    *,
    migrations: Sequence[Migration] | None = None,
) -> list[str]:
    """Apply outstanding migrations to *connection* and return applied IDs."""

    connection.execute("PRAGMA foreign_keys = ON")
    migrations = migrations or MIGRATIONS
    applied: list[str] = []
    with connection:
        _ensure_migrations_table(connection)
        completed = set(get_applied_migrations(connection))
        for migration in migrations:
            if migration.identifier in completed:
                continue
            for statement in migration.statements:
                connection.execute(statement)
            connection.execute(
                f"INSERT INTO {_MIGRATION_TABLE} (identifier, description) VALUES (?, ?)",
                (migration.identifier, migration.description),
            )
            applied.append(migration.identifier)
            completed.add(migration.identifier)
    return applied


def latest_migration_id(migrations: Iterable[Migration] | None = None) -> str | None:
    """Return the identifier of the most recent migration in *migrations*."""

    sequence = tuple(migrations) if migrations is not None else MIGRATIONS
    if not sequence:
        return None
    return sequence[-1].identifier
