"""SQLite persistence for settings, score summaries, and audit events."""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from typing import Any

from config import DATABASE_PATH


def _connect() -> sqlite3.Connection:
    parent = os.path.dirname(os.path.abspath(DATABASE_PATH))
    os.makedirs(parent, exist_ok=True)
    connection = sqlite3.connect(DATABASE_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    return connection


def init_db() -> None:
    with closing(_connect()) as connection, connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS analyses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                score REAL NOT NULL,
                score_breakdown TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_analyses_user_date
                ON analyses(username, created_at DESC);
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                event TEXT NOT NULL,
                details TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_audit_date
                ON audit_log(created_at DESC);
            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def record_audit_event(
    event: str, *, username: str = "anonymous", details: dict[str, Any] | None = None
) -> None:
    safe_details = details or {}
    with closing(_connect()) as connection, connection:
        connection.execute(
            "INSERT INTO audit_log(username, event, details, created_at) "
            "VALUES (?, ?, ?, ?)",
            (
                username[:100],
                event[:100],
                json.dumps(safe_details, ensure_ascii=True)[:2000],
                _now(),
            ),
        )


def save_analysis(
    username: str, score: float, score_breakdown: dict[str, float]
) -> None:
    with closing(_connect()) as connection, connection:
        connection.execute(
            "INSERT INTO analyses(username, score, score_breakdown, created_at) "
            "VALUES (?, ?, ?, ?)",
            (
                username[:100],
                score,
                json.dumps(score_breakdown, ensure_ascii=True),
                _now(),
            ),
        )


def get_user_analyses(username: str, limit: int = 20) -> list[dict[str, Any]]:
    with closing(_connect()) as connection, connection:
        rows = connection.execute(
            "SELECT score, score_breakdown, created_at FROM analyses "
            "WHERE username = ? ORDER BY created_at DESC LIMIT ?",
            (username, min(max(limit, 1), 100)),
        ).fetchall()
    return [
        {
            "score": row["score"],
            "score_breakdown": json.loads(row["score_breakdown"]),
            "created_at": row["created_at"],
        }
        for row in rows
    ]


def get_admin_analytics() -> dict[str, Any]:
    with closing(_connect()) as connection, connection:
        totals = connection.execute(
            "SELECT COUNT(*) AS total, AVG(score) AS average_score "
            "FROM analyses"
        ).fetchone()
        users = connection.execute(
            "SELECT COUNT(DISTINCT username) AS total FROM analyses"
        ).fetchone()
        latest = connection.execute(
            "SELECT username, score, created_at FROM analyses "
            "ORDER BY created_at DESC LIMIT 100"
        ).fetchall()
    return {
        "total_analyses": totals["total"],
        "average_score": totals["average_score"] or 0.0,
        "active_candidates": users["total"],
        "latest": [dict(row) for row in latest],
    }


def get_audit_events(limit: int = 200) -> list[dict[str, Any]]:
    with closing(_connect()) as connection, connection:
        rows = connection.execute(
            "SELECT username, event, details, created_at FROM audit_log "
            "ORDER BY created_at DESC LIMIT ?",
            (min(max(limit, 1), 500),),
        ).fetchall()
    return [
        {**dict(row), "details": json.loads(row["details"])}
        for row in rows
    ]


def get_setting(key: str) -> str | None:
    with closing(_connect()) as connection, connection:
        row = connection.execute(
            "SELECT value FROM app_settings WHERE key = ?", (key,)
        ).fetchone()
    return row["value"] if row else None


def set_setting(key: str, value: str) -> None:
    with closing(_connect()) as connection, connection:
        connection.execute(
            "INSERT INTO app_settings(key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, "
            "updated_at = excluded.updated_at",
            (key, value, _now()),
        )
