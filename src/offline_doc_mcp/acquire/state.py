"""Persistent acquisition state for resumable downloads."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class DownloadState:
    STATES = {"pending", "in_progress", "paused", "completed", "failed", "quarantined"}

    def __init__(self, database: Path | str):
        self.database = Path(database)
        self.database.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS downloads (
                    doc_id TEXT PRIMARY KEY, source TEXT NOT NULL, url TEXT NOT NULL,
                    expected_size INTEGER, expected_sha256 TEXT,
                    state TEXT NOT NULL, bytes_done INTEGER NOT NULL DEFAULT 0,
                    etag TEXT, last_modified TEXT, attempt_count INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT, next_retry_at TEXT, partial_path TEXT, final_path TEXT,
                    started_at TEXT, updated_at TEXT, completed_at TEXT
                )
            """)
            db.execute("CREATE INDEX IF NOT EXISTS downloads_state_idx ON downloads(state, updated_at)")

    def connect(self):
        return sqlite3.connect(self.database, timeout=15)

    def get(self, doc_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            db.row_factory = sqlite3.Row
            row = db.execute("SELECT * FROM downloads WHERE doc_id=?", (doc_id,)).fetchone()
            return dict(row) if row else None

    def ensure(self, *, doc_id: str, source: str, url: str, partial_path: Path,
               final_path: Path, expected_size: int | None = None,
               expected_sha256: str | None = None) -> dict[str, Any]:
        now = utcnow()
        with self.connect() as db:
            db.execute("""
                INSERT INTO downloads(doc_id,source,url,expected_size,expected_sha256,state,
                    partial_path,final_path,updated_at)
                VALUES(?,?,?,?,?,'pending',?,?,?)
                ON CONFLICT(doc_id) DO UPDATE SET
                    expected_size=COALESCE(excluded.expected_size,downloads.expected_size),
                    expected_sha256=COALESCE(excluded.expected_sha256,downloads.expected_sha256),
                    updated_at=excluded.updated_at
            """, (doc_id, source, url, expected_size, expected_sha256,
                  str(partial_path), str(final_path), now))
        result = self.get(doc_id)
        assert result is not None
        return result

    def update(self, doc_id: str, **values: Any) -> None:
        allowed = {
            "state", "bytes_done", "etag", "last_modified", "attempt_count",
            "last_error", "next_retry_at", "started_at", "completed_at",
            "expected_size", "expected_sha256",
        }
        if not values or set(values) - allowed:
            raise ValueError("Invalid download-state fields")
        if "state" in values and values["state"] not in self.STATES:
            raise ValueError("Invalid download state")
        values["updated_at"] = utcnow()
        assignments = ", ".join(f"{key}=?" for key in values)
        with self.connect() as db:
            db.execute(f"UPDATE downloads SET {assignments} WHERE doc_id=?",
                       (*values.values(), doc_id))

    def resumable(self) -> list[dict[str, Any]]:
        with self.connect() as db:
            db.row_factory = sqlite3.Row
            return [dict(row) for row in db.execute(
                "SELECT * FROM downloads WHERE state IN ('pending','paused','in_progress') ORDER BY updated_at"
            )]
