"""Transactional run state, request ledger, and resumable checkpoints."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .cache import atomic_write
from .config import BackfillConfig, canonical_json
from .planner import RequestSpec


SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    config_hash TEXT NOT NULL,
    config_json TEXT NOT NULL,
    status TEXT NOT NULL,
    next_sequence INTEGER NOT NULL,
    next_offset INTEGER NOT NULL,
    request_count INTEGER NOT NULL DEFAULT 0,
    cache_hit_count INTEGER NOT NULL DEFAULT 0,
    records_seen INTEGER NOT NULL DEFAULT 0,
    started_at_utc TEXT NOT NULL,
    updated_at_utc TEXT NOT NULL,
    completed_at_utc TEXT
);

CREATE TABLE IF NOT EXISTS requests (
    request_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    offset_value INTEGER NOT NULL,
    attempted_at_epoch REAL NOT NULL,
    attempted_at_utc TEXT NOT NULL,
    outcome TEXT NOT NULL,
    http_status INTEGER,
    response_sha256 TEXT,
    response_path TEXT,
    record_count INTEGER,
    error_text TEXT,
    FOREIGN KEY(run_id) REFERENCES runs(run_id)
);

CREATE TABLE IF NOT EXISTS pages (
    run_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    offset_value INTEGER NOT NULL,
    request_hash TEXT NOT NULL,
    source_kind TEXT NOT NULL,
    response_sha256 TEXT NOT NULL,
    response_path TEXT NOT NULL,
    record_count INTEGER NOT NULL,
    is_final_page INTEGER NOT NULL,
    accepted_at_utc TEXT NOT NULL,
    PRIMARY KEY(run_id, sequence),
    UNIQUE(run_id, offset_value),
    FOREIGN KEY(run_id) REFERENCES runs(run_id)
);

CREATE INDEX IF NOT EXISTS requests_attempted_at_idx
ON requests(attempted_at_epoch);
"""


def utc_now() -> datetime:
    """Return the current aware UTC timestamp."""
    return datetime.now(UTC)


class StateError(ValueError):
    """Raised when stored run state conflicts with the requested operation."""


class StateStore:
    """SQLite-backed state shared across resumable historical runs."""

    def __init__(self, path: Path):
        self.path = path.resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute("PRAGMA journal_mode = WAL")
        self.connection.executescript(SCHEMA)
        self.connection.commit()

    def close(self) -> None:
        """Close the state database."""
        self.connection.close()

    def __enter__(self) -> StateStore:
        return self

    def __exit__(self, *_) -> None:
        self.close()

    def initialize_run(
        self,
        config: BackfillConfig,
        *,
        now: datetime | None = None,
    ) -> None:
        """Create a run or verify that a resumable run has the same config."""
        timestamp = (now or utc_now()).astimezone(UTC).isoformat()
        existing = self.connection.execute(
            "SELECT config_hash, config_json FROM runs WHERE run_id = ?",
            (config.run_id,),
        ).fetchone()
        config_json = canonical_json(config.scope_payload())
        if existing is not None:
            if (
                existing["config_hash"] != config.config_hash
                or existing["config_json"] != config_json
            ):
                raise StateError(
                    f"Run {config.run_id} exists with a different configuration."
                )
            return

        with self.connection:
            self.connection.execute(
                """
                INSERT INTO runs (
                    run_id, config_hash, config_json, status,
                    next_sequence, next_offset, started_at_utc, updated_at_utc
                ) VALUES (?, ?, ?, 'planned', 1, 0, ?, ?)
                """,
                (
                    config.run_id,
                    config.config_hash,
                    config_json,
                    timestamp,
                    timestamp,
                ),
            )

    def run(self, run_id: str) -> dict[str, Any]:
        """Return one run as a dictionary."""
        row = self.connection.execute(
            "SELECT * FROM runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        if row is None:
            raise StateError(f"Unknown run: {run_id}")
        return dict(row)

    def accepted_pages(self, run_id: str) -> list[dict[str, Any]]:
        """Return accepted pages in deterministic sequence order."""
        rows = self.connection.execute(
            "SELECT * FROM pages WHERE run_id = ? ORDER BY sequence",
            (run_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def request_attempts(self, run_id: str) -> list[dict[str, Any]]:
        """Return the complete request ledger for one run."""
        rows = self.connection.execute(
            "SELECT * FROM requests WHERE run_id = ? ORDER BY request_id",
            (run_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def start_network_attempt(
        self,
        run_id: str,
        request: RequestSpec,
        *,
        attempted_at: datetime,
    ) -> int:
        """Persist an attempt before network I/O and increment the exact count."""
        attempted = attempted_at.astimezone(UTC)
        with self.connection:
            cursor = self.connection.execute(
                """
                INSERT INTO requests (
                    run_id, request_hash, sequence, offset_value,
                    attempted_at_epoch, attempted_at_utc, outcome
                ) VALUES (?, ?, ?, ?, ?, ?, 'started')
                """,
                (
                    run_id,
                    request.request_hash,
                    request.sequence,
                    request.offset,
                    attempted.timestamp(),
                    attempted.isoformat(),
                ),
            )
            self.connection.execute(
                """
                UPDATE runs
                SET request_count = request_count + 1,
                    status = CASE
                        WHEN status = 'planned' THEN 'running'
                        ELSE status
                    END,
                    updated_at_utc = ?
                WHERE run_id = ?
                """,
                (attempted.isoformat(), run_id),
            )
        return int(cursor.lastrowid)

    def finish_network_attempt(
        self,
        request_id: int,
        *,
        outcome: str,
        http_status: int | None = None,
        response_sha256: str | None = None,
        response_path: Path | None = None,
        record_count: int | None = None,
        error_text: str | None = None,
    ) -> None:
        """Finish a previously persisted network attempt."""
        with self.connection:
            cursor = self.connection.execute(
                """
                UPDATE requests
                SET outcome = ?, http_status = ?, response_sha256 = ?,
                    response_path = ?, record_count = ?, error_text = ?
                WHERE request_id = ? AND outcome = 'started'
                """,
                (
                    outcome,
                    http_status,
                    response_sha256,
                    str(response_path.resolve()) if response_path else None,
                    record_count,
                    error_text,
                    request_id,
                ),
            )
        if cursor.rowcount != 1:
            raise StateError(
                f"Network attempt {request_id} is missing or already finished."
            )

    def record_cache_hit(
        self,
        run_id: str,
        *,
        now: datetime | None = None,
    ) -> None:
        """Increment a local reuse counter without spending request budget."""
        timestamp = (now or utc_now()).astimezone(UTC).isoformat()
        with self.connection:
            self.connection.execute(
                """
                UPDATE runs
                SET cache_hit_count = cache_hit_count + 1,
                    updated_at_utc = ?
                WHERE run_id = ?
                """,
                (timestamp, run_id),
            )

    def accept_page(
        self,
        run_id: str,
        request: RequestSpec,
        *,
        source_kind: str,
        response_sha256: str,
        response_path: Path,
        record_count: int,
        is_final_page: bool,
        now: datetime | None = None,
    ) -> None:
        """Atomically accept a verified page and advance its checkpoint."""
        timestamp = (now or utc_now()).astimezone(UTC).isoformat()
        existing = self.connection.execute(
            "SELECT * FROM pages WHERE run_id = ? AND sequence = ?",
            (run_id, request.sequence),
        ).fetchone()
        if existing is not None:
            expected = (
                request.request_hash,
                response_sha256,
                str(response_path.resolve()),
                record_count,
                int(is_final_page),
            )
            actual = (
                existing["request_hash"],
                existing["response_sha256"],
                existing["response_path"],
                existing["record_count"],
                existing["is_final_page"],
            )
            if actual != expected:
                raise StateError(
                    f"Accepted page {request.sequence} conflicts with checkpoint."
                )
            return

        next_sequence = request.sequence + 1
        next_offset = request.offset + int(request.parameters["limit"])
        status = "complete" if is_final_page else "running"
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO pages (
                    run_id, sequence, offset_value, request_hash, source_kind,
                    response_sha256, response_path, record_count,
                    is_final_page, accepted_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    request.sequence,
                    request.offset,
                    request.request_hash,
                    source_kind,
                    response_sha256,
                    str(response_path.resolve()),
                    record_count,
                    int(is_final_page),
                    timestamp,
                ),
            )
            self.connection.execute(
                """
                UPDATE runs
                SET status = ?, next_sequence = ?, next_offset = ?,
                    records_seen = records_seen + ?, updated_at_utc = ?,
                    completed_at_utc = CASE WHEN ? = 'complete' THEN ? ELSE NULL END
                WHERE run_id = ?
                """,
                (
                    status,
                    next_sequence,
                    next_offset,
                    record_count,
                    timestamp,
                    status,
                    timestamp,
                    run_id,
                ),
            )

    def set_status(
        self,
        run_id: str,
        status: str,
        *,
        now: datetime | None = None,
    ) -> None:
        """Record a terminal or resumable run status."""
        allowed = {
            "planned",
            "running",
            "complete",
            "budget_exhausted",
            "failed",
        }
        if status not in allowed:
            raise ValueError(f"Unsupported run status: {status}")
        timestamp = (now or utc_now()).astimezone(UTC).isoformat()
        with self.connection:
            self.connection.execute(
                "UPDATE runs SET status = ?, updated_at_utc = ? WHERE run_id = ?",
                (status, timestamp, run_id),
            )

    def seconds_until_request_allowed(
        self,
        *,
        now: datetime,
        hourly_limit: int,
        minimum_interval_seconds: float,
    ) -> float:
        """Return the persistent sliding-window wait for another request."""
        current = now.astimezone(UTC).timestamp()
        recent = self.connection.execute(
            """
            SELECT attempted_at_epoch
            FROM requests
            WHERE attempted_at_epoch > ?
            ORDER BY attempted_at_epoch ASC
            """,
            (current - 3600,),
        ).fetchall()
        waits = [0.0]
        if recent:
            waits.append(
                recent[-1]["attempted_at_epoch"]
                + minimum_interval_seconds
                - current
            )
        if len(recent) >= hourly_limit:
            oldest_inside_limit = recent[-hourly_limit]["attempted_at_epoch"]
            waits.append(oldest_inside_limit + 3600 - current)
        return max(0.0, *waits)

    def write_checkpoint(
        self,
        config: BackfillConfig,
    ) -> Path:
        """Export a human-readable atomic checkpoint from transactional state."""
        run = self.run(config.run_id)
        payload = {
            "run": run,
            "scope": json.loads(run["config_json"]),
            "pages": self.accepted_pages(config.run_id),
            "requests": self.request_attempts(config.run_id),
        }
        checkpoint_path = config.run_directory / "checkpoint.json"
        atomic_write(
            checkpoint_path,
            (
                json.dumps(payload, indent=2, sort_keys=True)
                + "\n"
            ).encode("utf-8"),
        )
        return checkpoint_path
