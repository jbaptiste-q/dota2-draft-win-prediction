"""Immutable configuration for one historical backfill partition."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .contract import (
    ACQUISITION_VERSION,
    DEFAULT_HOURLY_REQUEST_LIMIT,
    DEFAULT_MAX_REQUESTS,
    DEFAULT_PAGE_SIZE,
    DEFAULT_REQUEST_INTERVAL_SECONDS,
    MATCH_FIELD_PROJECTION,
)


def utc_datetime(value: datetime) -> datetime:
    """Require an aware datetime and normalize it to whole-second UTC."""
    if value.tzinfo is None:
        raise ValueError("Backfill timestamps must include a timezone.")
    normalized = value.astimezone(UTC)
    if normalized.microsecond:
        raise ValueError("Backfill timestamps must use whole seconds.")
    return normalized


def parse_utc_datetime(value: str) -> datetime:
    """Parse an ISO-8601 timestamp and require explicit timezone information."""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"Invalid ISO-8601 timestamp: {value!r}") from error
    return utc_datetime(parsed)


def canonical_json(value: object) -> str:
    """Serialize a JSON-compatible value deterministically."""
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


@dataclass(frozen=True, slots=True)
class BackfillConfig:
    """One bounded, deterministic historical acquisition scope."""

    start_utc: datetime
    end_utc: datetime
    tiers: tuple[str, ...] = ("1", "2")
    patches: tuple[str, ...] = ()
    page_size: int = DEFAULT_PAGE_SIZE
    max_requests: int = DEFAULT_MAX_REQUESTS
    hourly_request_limit: int = DEFAULT_HOURLY_REQUEST_LIMIT
    request_interval_seconds: float = DEFAULT_REQUEST_INTERVAL_SECONDS
    raw_root: Path = Path("data/raw/liquipedia/backfill")
    run_root: Path = Path("data/backfill/runs")
    normalized_output_root: Path = Path("data/processed/liquipedia")
    projection: tuple[str, ...] = MATCH_FIELD_PROJECTION

    def __post_init__(self) -> None:
        start = utc_datetime(self.start_utc)
        end = utc_datetime(self.end_utc)
        if start >= end:
            raise ValueError("Backfill start must be earlier than end.")
        tiers = tuple(sorted({str(value).strip() for value in self.tiers}))
        if not tiers or any(not value for value in tiers):
            raise ValueError("At least one non-empty Liquipedia tier is required.")
        patches = tuple(sorted({value.strip() for value in self.patches if value.strip()}))
        if not 1 <= self.page_size <= 1000:
            raise ValueError("Page size must be between 1 and 1000.")
        if self.max_requests < 1:
            raise ValueError("Maximum request budget must be positive.")
        if not 1 <= self.hourly_request_limit <= 60:
            raise ValueError("Hourly request limit must be between 1 and 60.")
        minimum_interval = 3600 / self.hourly_request_limit
        if self.request_interval_seconds < minimum_interval:
            raise ValueError(
                "Request interval is too short for the configured hourly limit."
            )
        if not self.projection:
            raise ValueError("The match projection must not be empty.")

        object.__setattr__(self, "start_utc", start)
        object.__setattr__(self, "end_utc", end)
        object.__setattr__(self, "tiers", tiers)
        object.__setattr__(self, "patches", patches)

    def scope_payload(self) -> dict[str, object]:
        """Return the path-independent configuration used for identity."""
        return {
            "acquisition_version": ACQUISITION_VERSION,
            "start_utc": self.start_utc.isoformat(),
            "end_utc": self.end_utc.isoformat(),
            "tiers": list(self.tiers),
            "patches": list(self.patches),
            "patch_filter_stage": "normalized_training_dataset",
            "page_size": self.page_size,
            "max_requests": self.max_requests,
            "hourly_request_limit": self.hourly_request_limit,
            "request_interval_seconds": self.request_interval_seconds,
            "projection": list(self.projection),
        }

    @property
    def config_hash(self) -> str:
        """Return a stable SHA-256 identity for this acquisition scope."""
        return hashlib.sha256(
            canonical_json(self.scope_payload()).encode("utf-8")
        ).hexdigest()

    @property
    def run_id(self) -> str:
        """Return a readable deterministic run identity for resumption."""
        start = self.start_utc.strftime("%Y%m%d")
        end = self.end_utc.strftime("%Y%m%d")
        return f"m3_{start}_{end}_{self.config_hash[:12]}"

    @property
    def run_directory(self) -> Path:
        """Return the configured run-artifact directory."""
        return self.run_root / self.run_id

    @property
    def cache_directory(self) -> Path:
        """Return the global immutable response-cache directory."""
        return self.raw_root / "cache"

    @property
    def state_path(self) -> Path:
        """Return the shared transactional state database path."""
        return self.raw_root / "state.sqlite3"
