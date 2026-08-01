"""Transactional run state, request ledger, and resumable checkpoints."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

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

CREATE TABLE IF NOT EXISTS campaign_request_budgets (
    authorization_id TEXT PRIMARY KEY,
    plan_fingerprint TEXT NOT NULL UNIQUE,
    baseline_request_id INTEGER NOT NULL CHECK (baseline_request_id >= 0),
    baseline_total_attempts INTEGER NOT NULL
        CHECK (baseline_total_attempts >= 0),
    baseline_expansion_attempts INTEGER NOT NULL
        CHECK (baseline_expansion_attempts >= 0),
    baseline_excluded_run_ids_json TEXT NOT NULL,
    maximum_new_attempts INTEGER NOT NULL CHECK (maximum_new_attempts > 0),
    activated_at_utc TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1))
);

CREATE UNIQUE INDEX IF NOT EXISTS one_active_campaign_request_budget_idx
ON campaign_request_budgets(is_active)
WHERE is_active = 1;

CREATE TABLE IF NOT EXISTS campaign_request_budget_allowed_runs (
    authorization_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    maximum_attempts INTEGER NOT NULL CHECK (maximum_attempts > 0),
    PRIMARY KEY(authorization_id, run_id),
    FOREIGN KEY(authorization_id)
        REFERENCES campaign_request_budgets(authorization_id)
);
"""


def utc_now() -> datetime:
    """Return the current aware UTC timestamp."""
    return datetime.now(UTC)


class StateError(ValueError):
    """Raised when stored run state conflicts with the requested operation."""


RECOVERED_READ_TIMEOUT_ERROR = (
    "Liquipedia API request failed: response body read timed out before any "
    "response metadata or payload was persisted"
)


def is_no_response_transport_failure(row: Mapping[str, Any]) -> bool:
    """Identify a charged attempt that received no HTTP response or payload."""
    return (
        row.get("outcome") == "http_error"
        and row.get("http_status") is None
        and row.get("response_sha256") is None
        and row.get("response_path") is None
        and row.get("record_count") is None
        and str(row.get("error_text") or "").startswith(
            "Liquipedia API request failed:"
        )
    )


def is_no_payload_gateway_timeout(row: Mapping[str, Any]) -> bool:
    """Identify an HTTP 504 attempt with no persisted response payload."""
    return (
        row.get("outcome") == "http_error"
        and row.get("http_status") == 504
        and row.get("response_sha256") is None
        and row.get("response_path") is None
        and row.get("record_count") is None
    )


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

    @staticmethod
    def _normalize_campaign_budget_inputs(
        *,
        authorization_id: str,
        plan_fingerprint: str,
        baseline_request_id: int,
        baseline_total_attempts: int,
        baseline_expansion_attempts: int,
        maximum_new_attempts: int,
        allowed_runs: Mapping[str, int],
        baseline_excluded_run_ids: Sequence[str],
    ) -> tuple[dict[str, Any], dict[str, int], tuple[str, ...]]:
        """Validate and canonicalize one immutable authorization contract."""
        if not authorization_id.strip():
            raise ValueError("Authorization ID must not be empty.")
        if not plan_fingerprint.strip():
            raise ValueError("Plan fingerprint must not be empty.")
        if baseline_request_id < 0 or baseline_total_attempts < 0:
            raise ValueError(
                "Campaign request-budget baselines cannot be negative."
            )
        if baseline_expansion_attempts < 0:
            raise ValueError("Expansion-attempt baseline cannot be negative.")
        if maximum_new_attempts < 1:
            raise ValueError("Maximum new attempts must be positive.")
        normalized_allowed_runs = {
            str(run_id).strip(): int(maximum_attempts)
            for run_id, maximum_attempts in allowed_runs.items()
        }
        if (
            not normalized_allowed_runs
            or any(not run_id for run_id in normalized_allowed_runs)
            or any(value < 1 for value in normalized_allowed_runs.values())
        ):
            raise ValueError(
                "Allowed campaign runs require non-empty IDs and positive caps."
            )
        normalized_excluded_run_ids = tuple(
            sorted(
                {
                    str(run_id).strip()
                    for run_id in baseline_excluded_run_ids
                }
            )
        )
        if any(not run_id for run_id in normalized_excluded_run_ids):
            raise ValueError("Excluded baseline run IDs must not be empty.")

        requested = {
            "authorization_id": authorization_id,
            "plan_fingerprint": plan_fingerprint,
            "baseline_request_id": baseline_request_id,
            "baseline_total_attempts": baseline_total_attempts,
            "baseline_expansion_attempts": baseline_expansion_attempts,
            "baseline_excluded_run_ids_json": canonical_json(
                list(normalized_excluded_run_ids)
            ),
            "maximum_new_attempts": maximum_new_attempts,
        }
        return (
            requested,
            normalized_allowed_runs,
            normalized_excluded_run_ids,
        )

    def activate_campaign_request_budget(
        self,
        *,
        authorization_id: str,
        plan_fingerprint: str,
        baseline_request_id: int,
        baseline_total_attempts: int,
        baseline_expansion_attempts: int,
        maximum_new_attempts: int,
        allowed_runs: Mapping[str, int],
        baseline_excluded_run_ids: Sequence[str] = (),
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Bind one immutable live-request authorization to the current ledger.

        The first activation succeeds only when the complete ledger exactly
        matches the reviewed baseline. Replaying the exact same authorization
        is idempotent; changing any bound value is rejected.
        """
        (
            requested,
            normalized_allowed_runs,
            normalized_excluded_run_ids,
        ) = self._normalize_campaign_budget_inputs(
            authorization_id=authorization_id,
            plan_fingerprint=plan_fingerprint,
            baseline_request_id=baseline_request_id,
            baseline_total_attempts=baseline_total_attempts,
            baseline_expansion_attempts=baseline_expansion_attempts,
            maximum_new_attempts=maximum_new_attempts,
            allowed_runs=allowed_runs,
            baseline_excluded_run_ids=baseline_excluded_run_ids,
        )
        timestamp = (now or utc_now()).astimezone(UTC).isoformat()

        self.connection.execute("BEGIN IMMEDIATE")
        try:
            existing = self.connection.execute(
                """
                SELECT *
                FROM campaign_request_budgets
                WHERE authorization_id = ?
                """,
                (authorization_id,),
            ).fetchone()
            if existing is not None:
                actual = {
                    key: existing[key]
                    for key in requested
                }
                actual_allowed_runs = self._campaign_allowed_runs_locked(
                    authorization_id
                )
                if (
                    actual != requested
                    or actual_allowed_runs != normalized_allowed_runs
                    or existing["is_active"] != 1
                ):
                    raise StateError(
                        "Campaign request-budget authorization replay differs "
                        "from the immutable stored authorization."
                    )
                self._validate_campaign_budget_ledger_locked(existing)
                self.connection.commit()
                return self.campaign_request_budget(authorization_id)

            active = self.connection.execute(
                """
                SELECT authorization_id
                FROM campaign_request_budgets
                WHERE is_active = 1
                """
            ).fetchone()
            if active is not None:
                raise StateError(
                    "A different campaign request-budget authorization is active: "
                    f"{active['authorization_id']}."
                )

            self._validate_activation_baseline_locked(
                baseline_request_id=baseline_request_id,
                baseline_total_attempts=baseline_total_attempts,
                baseline_expansion_attempts=baseline_expansion_attempts,
                baseline_excluded_run_ids=normalized_excluded_run_ids,
            )
            self.connection.execute(
                """
                INSERT INTO campaign_request_budgets (
                    authorization_id, plan_fingerprint, baseline_request_id,
                    baseline_total_attempts, baseline_expansion_attempts,
                    baseline_excluded_run_ids_json, maximum_new_attempts,
                    activated_at_utc, is_active
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
                """,
                (
                    authorization_id,
                    plan_fingerprint,
                    baseline_request_id,
                    baseline_total_attempts,
                    baseline_expansion_attempts,
                    requested["baseline_excluded_run_ids_json"],
                    maximum_new_attempts,
                    timestamp,
                ),
            )
            self.connection.executemany(
                """
                INSERT INTO campaign_request_budget_allowed_runs (
                    authorization_id, run_id, maximum_attempts
                ) VALUES (?, ?, ?)
                """,
                (
                    (authorization_id, run_id, maximum_attempts)
                    for run_id, maximum_attempts in sorted(
                        normalized_allowed_runs.items()
                    )
                ),
            )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        return self.campaign_request_budget(authorization_id)

    def supersede_campaign_request_budget(
        self,
        *,
        predecessor_authorization_id: str,
        authorization_id: str,
        plan_fingerprint: str,
        baseline_request_id: int,
        baseline_total_attempts: int,
        baseline_expansion_attempts: int,
        maximum_new_attempts: int,
        allowed_runs: Mapping[str, int],
        baseline_excluded_run_ids: Sequence[str] = (),
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Atomically replace one exactly exhausted authorization.

        The predecessor remains immutable and queryable with ``is_active``
        false. Its stored ceiling and the successor's exact ledger baseline
        form the historical handoff boundary. Exact successor replays are
        idempotent, while any changed contract fails closed.
        """
        if not predecessor_authorization_id.strip():
            raise ValueError("Predecessor authorization ID must not be empty.")
        if predecessor_authorization_id == authorization_id:
            raise StateError(
                "A successor authorization must have a new authorization ID."
            )
        (
            requested,
            normalized_allowed_runs,
            normalized_excluded_run_ids,
        ) = self._normalize_campaign_budget_inputs(
            authorization_id=authorization_id,
            plan_fingerprint=plan_fingerprint,
            baseline_request_id=baseline_request_id,
            baseline_total_attempts=baseline_total_attempts,
            baseline_expansion_attempts=baseline_expansion_attempts,
            maximum_new_attempts=maximum_new_attempts,
            allowed_runs=allowed_runs,
            baseline_excluded_run_ids=baseline_excluded_run_ids,
        )
        timestamp = (now or utc_now()).astimezone(UTC).isoformat()

        self.connection.execute("BEGIN IMMEDIATE")
        try:
            predecessor = self.connection.execute(
                """
                SELECT *
                FROM campaign_request_budgets
                WHERE authorization_id = ?
                """,
                (predecessor_authorization_id,),
            ).fetchone()
            existing = self.connection.execute(
                """
                SELECT *
                FROM campaign_request_budgets
                WHERE authorization_id = ?
                """,
                (authorization_id,),
            ).fetchone()

            if existing is not None:
                actual = {key: existing[key] for key in requested}
                actual_allowed_runs = self._campaign_allowed_runs_locked(
                    authorization_id
                )
                active = self.connection.execute(
                    """
                    SELECT authorization_id
                    FROM campaign_request_budgets
                    WHERE is_active = 1
                    """
                ).fetchone()
                if (
                    predecessor is None
                    or predecessor["is_active"] != 0
                    or actual != requested
                    or actual_allowed_runs != normalized_allowed_runs
                    or existing["is_active"] != 1
                    or active is None
                    or active["authorization_id"] != authorization_id
                ):
                    raise StateError(
                        "Campaign request-budget successor replay differs "
                        "from the immutable stored handoff."
                    )
                self._validate_campaign_budget_ledger_locked(existing)
                self.connection.commit()
                result = self.campaign_request_budget(authorization_id)
                if result is None:
                    raise StateError(
                        "Successor authorization disappeared after replay."
                    )
                return result

            if predecessor is None:
                raise StateError(
                    "The predecessor campaign authorization does not exist."
                )
            active = self.connection.execute(
                """
                SELECT authorization_id
                FROM campaign_request_budgets
                WHERE is_active = 1
                """
            ).fetchone()
            if (
                predecessor["is_active"] != 1
                or active is None
                or active["authorization_id"]
                != predecessor_authorization_id
            ):
                raise StateError(
                    "The named predecessor is not the active campaign "
                    "authorization."
                )
            if predecessor["plan_fingerprint"] == plan_fingerprint:
                raise StateError(
                    "A successor authorization requires a new plan fingerprint."
                )

            predecessor_accounting = (
                self._validate_campaign_budget_ledger_locked(predecessor)
            )
            if predecessor_accounting["unresolved_started_attempts"]:
                raise StateError(
                    "An authorization with an unresolved request cannot be "
                    "superseded."
                )
            if (
                predecessor_accounting["new_attempts_used"]
                != predecessor_accounting["maximum_new_attempts"]
                or predecessor_accounting["remaining_new_attempts"] != 0
            ):
                raise StateError(
                    "Only an exactly exhausted campaign authorization can be "
                    "superseded."
                )

            predecessor_excluded_run_ids = tuple(
                json.loads(
                    predecessor["baseline_excluded_run_ids_json"]
                )
            )
            if (
                normalized_excluded_run_ids
                != predecessor_excluded_run_ids
            ):
                raise StateError(
                    "A successor cannot change baseline exclusion semantics."
                )
            predecessor_allowed_runs = set(
                predecessor_accounting["allowed_runs"]
            )
            if not set(normalized_allowed_runs).issubset(
                predecessor_allowed_runs
            ):
                raise StateError(
                    "A successor cannot broaden the predecessor run allowlist."
                )
            if (
                baseline_request_id
                != predecessor_accounting["total_attempts"]
                or baseline_total_attempts
                != predecessor_accounting["total_attempts"]
                or baseline_expansion_attempts
                != predecessor_accounting[
                    "cumulative_expansion_attempts"
                ]
            ):
                raise StateError(
                    "Successor baselines must equal the exhausted "
                    "predecessor's current ledger boundary."
                )
            self._validate_activation_baseline_locked(
                baseline_request_id=baseline_request_id,
                baseline_total_attempts=baseline_total_attempts,
                baseline_expansion_attempts=baseline_expansion_attempts,
                baseline_excluded_run_ids=normalized_excluded_run_ids,
            )

            updated = self.connection.execute(
                """
                UPDATE campaign_request_budgets
                SET is_active = 0
                WHERE authorization_id = ? AND is_active = 1
                """,
                (predecessor_authorization_id,),
            )
            if updated.rowcount != 1:
                raise StateError(
                    "The predecessor authorization changed during handoff."
                )
            self.connection.execute(
                """
                INSERT INTO campaign_request_budgets (
                    authorization_id, plan_fingerprint, baseline_request_id,
                    baseline_total_attempts, baseline_expansion_attempts,
                    baseline_excluded_run_ids_json, maximum_new_attempts,
                    activated_at_utc, is_active
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
                """,
                (
                    authorization_id,
                    plan_fingerprint,
                    baseline_request_id,
                    baseline_total_attempts,
                    baseline_expansion_attempts,
                    requested["baseline_excluded_run_ids_json"],
                    maximum_new_attempts,
                    timestamp,
                ),
            )
            self.connection.executemany(
                """
                INSERT INTO campaign_request_budget_allowed_runs (
                    authorization_id, run_id, maximum_attempts
                ) VALUES (?, ?, ?)
                """,
                (
                    (authorization_id, run_id, maximum_attempts)
                    for run_id, maximum_attempts in sorted(
                        normalized_allowed_runs.items()
                    )
                ),
            )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise

        result = self.campaign_request_budget(authorization_id)
        if result is None:
            raise StateError("Successor authorization disappeared after handoff.")
        return result

    def campaign_request_budget(
        self,
        authorization_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Return one immutable campaign authorization without credentials."""
        if authorization_id is None:
            row = self.connection.execute(
                """
                SELECT *
                FROM campaign_request_budgets
                WHERE is_active = 1
                """
            ).fetchone()
        else:
            row = self.connection.execute(
                """
                SELECT *
                FROM campaign_request_budgets
                WHERE authorization_id = ?
                """,
                (authorization_id,),
            ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["is_active"] = bool(result["is_active"])
        result["baseline_excluded_run_ids"] = json.loads(
            result.pop("baseline_excluded_run_ids_json")
        )
        result["allowed_runs"] = self._campaign_allowed_runs_locked(
            result["authorization_id"]
        )
        return result

    def campaign_request_budget_accounting(
        self,
        authorization_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Return fail-closed campaign request accounting from the ledger."""
        if authorization_id is None:
            row = self.connection.execute(
                """
                SELECT *
                FROM campaign_request_budgets
                WHERE is_active = 1
                """
            ).fetchone()
        else:
            row = self.connection.execute(
                """
                SELECT *
                FROM campaign_request_budgets
                WHERE authorization_id = ?
                """,
                (authorization_id,),
            ).fetchone()
        if row is None:
            return None
        return self._validate_campaign_budget_ledger_locked(row)

    def start_network_attempt(
        self,
        run_id: str,
        request: RequestSpec,
        *,
        attempted_at: datetime,
    ) -> int:
        """Persist an attempt before network I/O and increment the exact count."""
        attempted = attempted_at.astimezone(UTC)
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            active_budget = self.connection.execute(
                """
                SELECT *
                FROM campaign_request_budgets
                WHERE is_active = 1
                """
            ).fetchone()
            if active_budget is not None:
                accounting = self._validate_campaign_budget_ledger_locked(
                    active_budget
                )
                allowed_runs = accounting["allowed_runs"]
                if run_id not in allowed_runs:
                    raise StateError(
                        f"Run {run_id} is not authorized by campaign request "
                        f"budget {active_budget['authorization_id']}."
                    )
                if accounting["unresolved_started_attempts"]:
                    raise StateError(
                        "The campaign request ledger contains an unresolved "
                        "'started' attempt; no additional request may begin."
                    )
                if (
                    accounting["new_attempts_used"]
                    >= active_budget["maximum_new_attempts"]
                ):
                    raise StateError(
                        "The campaign-wide maximum number of new request "
                        "attempts has been reached."
                    )
                if (
                    accounting["per_run_attempts"][run_id]
                    >= allowed_runs[run_id]
                ):
                    raise StateError(
                        f"Run {run_id} has reached its authorized request cap "
                        f"of {allowed_runs[run_id]}."
                    )
                duplicates = self.connection.execute(
                    """
                    SELECT *
                    FROM requests
                    WHERE request_id > ?
                      AND run_id = ?
                      AND (
                          request_hash = ?
                          OR sequence = ?
                          OR offset_value = ?
                    )
                    ORDER BY request_id
                    """,
                    (
                        active_budget["baseline_request_id"],
                        run_id,
                        request.request_hash,
                        request.sequence,
                        request.offset,
                    ),
                ).fetchall()
                retryable_transport_failure = (
                    len(duplicates) == 1
                    and is_no_response_transport_failure(
                        dict(duplicates[0])
                    )
                    and self._request_attempt_matches(
                        duplicates[0],
                        run_id=run_id,
                        request=request,
                    )
                )
                retryable_gateway_timeout = (
                    len(duplicates) == 2
                    and is_no_response_transport_failure(
                        dict(duplicates[0])
                    )
                    and is_no_payload_gateway_timeout(
                        dict(duplicates[1])
                    )
                    and all(
                        self._request_attempt_matches(
                            duplicate,
                            run_id=run_id,
                            request=request,
                        )
                        for duplicate in duplicates
                    )
                )
                if duplicates and not (
                    retryable_transport_failure
                    or retryable_gateway_timeout
                ):
                    raise StateError(
                        "Campaign request ledger already contains a "
                        "post-activation attempt for this run and request "
                        "hash, sequence, or offset; another attempt is not "
                        "authorized "
                        f"(request_id={duplicates[0]['request_id']})."
                    )

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
            updated = self.connection.execute(
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
            if updated.rowcount != 1:
                raise StateError(f"Unknown run: {run_id}")
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        return int(cursor.lastrowid)

    @staticmethod
    def _request_attempt_matches(
        row: Mapping[str, Any],
        *,
        run_id: str,
        request: RequestSpec,
    ) -> bool:
        """Return whether a ledger row is the exact requested page slot."""
        values = dict(row)
        return (
            values.get("run_id") == run_id
            and values.get("request_hash") == request.request_hash
            and int(values.get("sequence", -1)) == request.sequence
            and int(values.get("offset_value", -1)) == request.offset
        )

    def _campaign_allowed_runs_locked(
        self,
        authorization_id: str,
    ) -> dict[str, int]:
        rows = self.connection.execute(
            """
            SELECT run_id, maximum_attempts
            FROM campaign_request_budget_allowed_runs
            WHERE authorization_id = ?
            ORDER BY run_id
            """,
            (authorization_id,),
        ).fetchall()
        return {
            row["run_id"]: int(row["maximum_attempts"])
            for row in rows
        }

    def _sqlite_request_sequence_locked(self) -> int:
        row = self.connection.execute(
            """
            SELECT seq
            FROM sqlite_sequence
            WHERE name = 'requests'
            """
        ).fetchone()
        return int(row["seq"]) if row is not None else 0

    def _validate_activation_baseline_locked(
        self,
        *,
        baseline_request_id: int,
        baseline_total_attempts: int,
        baseline_expansion_attempts: int,
        baseline_excluded_run_ids: Sequence[str],
    ) -> None:
        ledger = self.connection.execute(
            """
            SELECT
                COUNT(*) AS total_attempts,
                COALESCE(MIN(request_id), 0) AS minimum_request_id,
                COALESCE(MAX(request_id), 0) AS maximum_request_id,
                SUM(CASE WHEN outcome = 'started' THEN 1 ELSE 0 END)
                    AS unresolved_started_attempts
            FROM requests
            """
        ).fetchone()
        sequence = self._sqlite_request_sequence_locked()
        expected_minimum = 1 if baseline_total_attempts else 0
        if (
            ledger["total_attempts"] != baseline_total_attempts
            or ledger["minimum_request_id"] != expected_minimum
            or ledger["maximum_request_id"] != baseline_request_id
            or sequence != baseline_request_id
            or baseline_total_attempts != baseline_request_id
        ):
            raise StateError(
                "Campaign request-budget activation baseline does not match "
                "the complete contiguous request ledger."
            )
        if ledger["unresolved_started_attempts"]:
            raise StateError(
                "Campaign request-budget activation requires zero unresolved "
                "'started' attempts."
            )

        if baseline_excluded_run_ids:
            placeholders = ",".join("?" for _ in baseline_excluded_run_ids)
            expansion = self.connection.execute(
                f"""
                SELECT COUNT(*) AS attempt_count
                FROM requests
                WHERE request_id <= ?
                  AND run_id NOT IN ({placeholders})
                """,
                (baseline_request_id, *baseline_excluded_run_ids),
            ).fetchone()
        else:
            expansion = self.connection.execute(
                """
                SELECT COUNT(*) AS attempt_count
                FROM requests
                WHERE request_id <= ?
                """,
                (baseline_request_id,),
            ).fetchone()
        if expansion["attempt_count"] != baseline_expansion_attempts:
            raise StateError(
                "Campaign request-budget activation expansion-attempt "
                "baseline does not match the request ledger."
            )

    def _validate_campaign_budget_ledger_locked(
        self,
        budget: sqlite3.Row,
    ) -> dict[str, Any]:
        baseline_request_id = int(budget["baseline_request_id"])
        baseline_total_attempts = int(budget["baseline_total_attempts"])
        baseline_expansion_attempts = int(
            budget["baseline_expansion_attempts"]
        )
        maximum_new_attempts = int(budget["maximum_new_attempts"])
        allowed_runs = self._campaign_allowed_runs_locked(
            budget["authorization_id"]
        )
        if not allowed_runs:
            raise StateError(
                "Active campaign request-budget authorization has no allowed runs."
            )

        ledger = self.connection.execute(
            """
            SELECT
                COUNT(*) AS total_attempts,
                COALESCE(MIN(request_id), 0) AS minimum_request_id,
                COALESCE(MAX(request_id), 0) AS maximum_request_id,
                COALESCE(SUM(
                    CASE
                        WHEN request_id > ? THEN 1
                        ELSE 0
                    END
                ), 0) AS new_attempts,
                COALESCE(SUM(
                    CASE
                        WHEN request_id > ? AND outcome = 'started' THEN 1
                        ELSE 0
                    END
                ), 0) AS unresolved_started_attempts
            FROM requests
            """,
            (baseline_request_id, baseline_request_id),
        ).fetchone()
        baseline = self.connection.execute(
            """
            SELECT
                COUNT(*) AS total_attempts,
                COALESCE(MIN(request_id), 0) AS minimum_request_id,
                COALESCE(MAX(request_id), 0) AS maximum_request_id
            FROM requests
            WHERE request_id <= ?
            """,
            (baseline_request_id,),
        ).fetchone()
        new_attempts = int(ledger["new_attempts"])
        expected_maximum = baseline_request_id + new_attempts
        sequence = self._sqlite_request_sequence_locked()
        if (
            baseline["total_attempts"] != baseline_total_attempts
            or baseline["minimum_request_id"] != (
                1 if baseline_total_attempts else 0
            )
            or baseline["maximum_request_id"] != baseline_request_id
            or baseline_total_attempts != baseline_request_id
            or ledger["total_attempts"]
            != baseline_total_attempts + new_attempts
            or ledger["maximum_request_id"] != expected_maximum
            or sequence != expected_maximum
        ):
            raise StateError(
                "Campaign request ledger is discontinuous or a request row "
                "has been deleted."
            )

        excluded_run_ids = tuple(
            json.loads(budget["baseline_excluded_run_ids_json"])
        )
        if excluded_run_ids:
            placeholders = ",".join("?" for _ in excluded_run_ids)
            expansion = self.connection.execute(
                f"""
                SELECT COUNT(*) AS attempt_count
                FROM requests
                WHERE request_id <= ?
                  AND run_id NOT IN ({placeholders})
                """,
                (baseline_request_id, *excluded_run_ids),
            ).fetchone()
        else:
            expansion = self.connection.execute(
                """
                SELECT COUNT(*) AS attempt_count
                FROM requests
                WHERE request_id <= ?
                """,
                (baseline_request_id,),
            ).fetchone()
        if expansion["attempt_count"] != baseline_expansion_attempts:
            raise StateError(
                "Campaign request ledger no longer matches the authorized "
                "expansion-attempt baseline."
            )

        unauthorized = self.connection.execute(
            """
            SELECT requests.run_id
            FROM requests
            LEFT JOIN campaign_request_budget_allowed_runs AS allowed
              ON allowed.authorization_id = ?
             AND allowed.run_id = requests.run_id
            WHERE requests.request_id > ?
              AND allowed.run_id IS NULL
            ORDER BY requests.request_id
            LIMIT 1
            """,
            (budget["authorization_id"], baseline_request_id),
        ).fetchone()
        if unauthorized is not None:
            raise StateError(
                "Campaign request ledger contains a post-activation attempt "
                f"for unauthorized run {unauthorized['run_id']}."
            )

        per_run_attempts = {run_id: 0 for run_id in allowed_runs}
        rows = self.connection.execute(
            """
            SELECT run_id, COUNT(*) AS attempt_count
            FROM requests
            WHERE request_id > ?
            GROUP BY run_id
            ORDER BY run_id
            """,
            (baseline_request_id,),
        ).fetchall()
        for row in rows:
            per_run_attempts[row["run_id"]] = int(row["attempt_count"])
        over_cap = [
            run_id
            for run_id, attempt_count in per_run_attempts.items()
            if attempt_count > allowed_runs[run_id]
        ]
        if over_cap:
            raise StateError(
                "Campaign request ledger exceeds the authorized per-run cap "
                f"for {over_cap[0]}."
            )
        if new_attempts > maximum_new_attempts:
            raise StateError(
                "Campaign request ledger exceeds the campaign-wide maximum "
                "number of new attempts."
            )

        return {
            "authorization_id": budget["authorization_id"],
            "plan_fingerprint": budget["plan_fingerprint"],
            "baseline_request_id": baseline_request_id,
            "baseline_total_attempts": baseline_total_attempts,
            "baseline_expansion_attempts": baseline_expansion_attempts,
            "maximum_new_attempts": maximum_new_attempts,
            "new_attempts_used": new_attempts,
            "remaining_new_attempts": maximum_new_attempts - new_attempts,
            "cumulative_expansion_attempts": (
                baseline_expansion_attempts + new_attempts
            ),
            "cumulative_expansion_attempt_ceiling": (
                baseline_expansion_attempts + maximum_new_attempts
            ),
            "total_attempts": baseline_total_attempts + new_attempts,
            "total_attempt_ceiling": (
                baseline_total_attempts + maximum_new_attempts
            ),
            "unresolved_started_attempts": int(
                ledger["unresolved_started_attempts"]
            ),
            "allowed_runs": allowed_runs,
            "per_run_attempts": per_run_attempts,
            "ledger_contiguous": True,
        }

    def recover_latest_started_read_timeout(
        self,
        *,
        request_id: int,
        run_id: str,
        sequence: int,
        offset_value: int,
        request_hash: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Close one exact latest orphaned attempt after a read timeout.

        This method records no exception details. It accepts only a charged
        post-authorization attempt that is still ``started`` and has received
        no HTTP or response metadata. The request and run transition happen
        in one transaction; the caller writes the resulting checkpoint.
        """
        if request_id < 1:
            raise ValueError("Recovered request ID must be positive.")
        if not run_id.strip():
            raise ValueError("Recovered run ID must not be empty.")
        if sequence < 1 or offset_value < 0:
            raise ValueError(
                "Recovered request sequence and offset are invalid."
            )
        if not request_hash.strip():
            raise ValueError("Recovered request hash must not be empty.")
        timestamp = (now or utc_now()).astimezone(UTC).isoformat()

        self.connection.execute("BEGIN IMMEDIATE")
        try:
            active_budget = self.connection.execute(
                """
                SELECT *
                FROM campaign_request_budgets
                WHERE is_active = 1
                """
            ).fetchone()
            if active_budget is None:
                raise StateError(
                    "A started timeout attempt requires an active campaign "
                    "authorization."
                )
            accounting = self._validate_campaign_budget_ledger_locked(
                active_budget
            )
            if run_id not in accounting["allowed_runs"]:
                raise StateError(
                    "The timeout attempt run is not authorized by the active "
                    "campaign budget."
                )
            if request_id <= int(active_budget["baseline_request_id"]):
                raise StateError(
                    "The timeout attempt predates the active authorization."
                )
            if accounting["unresolved_started_attempts"] != 1:
                raise StateError(
                    "Timeout recovery requires exactly one unresolved "
                    "started attempt."
                )

            latest = self.connection.execute(
                """
                SELECT MAX(request_id) AS request_id
                FROM requests
                """
            ).fetchone()
            if latest is None or int(latest["request_id"] or 0) != request_id:
                raise StateError(
                    "Only the latest request-ledger row can be recovered."
                )
            attempt = self.connection.execute(
                """
                SELECT *
                FROM requests
                WHERE request_id = ?
                """,
                (request_id,),
            ).fetchone()
            if attempt is None:
                raise StateError("The timeout attempt does not exist.")
            expected_contract = (
                run_id,
                sequence,
                offset_value,
                request_hash,
            )
            actual_contract = (
                attempt["run_id"],
                int(attempt["sequence"]),
                int(attempt["offset_value"]),
                attempt["request_hash"],
            )
            if actual_contract != expected_contract:
                raise StateError(
                    "The timeout attempt conflicts with the exact request "
                    "contract."
                )
            if attempt["outcome"] != "started":
                raise StateError(
                    "The timeout attempt is no longer in started state."
                )
            response_fields = (
                attempt["http_status"],
                attempt["response_sha256"],
                attempt["response_path"],
                attempt["record_count"],
                attempt["error_text"],
            )
            if any(value is not None for value in response_fields):
                raise StateError(
                    "The timeout attempt already contains HTTP or response "
                    "metadata."
                )

            updated_attempt = self.connection.execute(
                """
                UPDATE requests
                SET outcome = 'http_error',
                    error_text = ?
                WHERE request_id = ?
                  AND run_id = ?
                  AND sequence = ?
                  AND offset_value = ?
                  AND request_hash = ?
                  AND outcome = 'started'
                  AND http_status IS NULL
                  AND response_sha256 IS NULL
                  AND response_path IS NULL
                  AND record_count IS NULL
                  AND error_text IS NULL
                """,
                (
                    RECOVERED_READ_TIMEOUT_ERROR,
                    request_id,
                    run_id,
                    sequence,
                    offset_value,
                    request_hash,
                ),
            )
            if updated_attempt.rowcount != 1:
                raise StateError(
                    "The timeout attempt changed during recovery."
                )
            updated_run = self.connection.execute(
                """
                UPDATE runs
                SET status = 'failed', updated_at_utc = ?
                WHERE run_id = ?
                """,
                (timestamp, run_id),
            )
            if updated_run.rowcount != 1:
                raise StateError(
                    "The timeout attempt run disappeared during recovery."
                )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise

        recovered = self.connection.execute(
            """
            SELECT *
            FROM requests
            WHERE request_id = ?
            """,
            (request_id,),
        ).fetchone()
        if recovered is None:
            raise StateError("Recovered timeout attempt disappeared.")
        return dict(recovered)

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
