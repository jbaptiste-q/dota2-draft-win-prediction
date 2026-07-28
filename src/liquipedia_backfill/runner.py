"""Checkpointed acquisition runner with cache-first page traversal."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

from .cache import CacheError, CacheStore, atomic_write, sha256_bytes
from .client import ApiRequestError, HttpResponse, request_page
from .config import BackfillConfig
from .envelope import ResponseEnvelopeError, response_record_count
from .planner import RequestSpec, request_spec
from .state import StateStore


@dataclass(frozen=True, slots=True)
class AcquisitionRunResult:
    """Terminal or resumable state after one runner invocation."""

    run_id: str
    status: str
    request_count: int
    cache_hit_count: int
    records_seen: int
    accepted_page_count: int
    checkpoint_path: Path


Fetcher = Callable[[RequestSpec, str, float], HttpResponse]


def default_fetcher(
    spec: RequestSpec,
    api_key: str,
    timeout_seconds: float,
) -> HttpResponse:
    """Adapt the official client to the injectable runner interface."""
    return request_page(
        spec,
        api_key=api_key,
        timeout_seconds=timeout_seconds,
    )


class BackfillRunner:
    """Run a bounded cache-first partition with persistent rate accounting."""

    def __init__(
        self,
        *,
        fetcher: Fetcher = default_fetcher,
        clock: Callable[[], datetime] | None = None,
        sleeper: Callable[[float], None] = time.sleep,
    ):
        self.fetcher = fetcher
        self.clock = clock or (lambda: datetime.now(UTC))
        self.sleeper = sleeper

    def _failure_path(
        self,
        config: BackfillConfig,
        spec: RequestSpec,
        body: bytes,
    ) -> Path:
        response_sha = sha256_bytes(body)
        return (
            config.run_directory
            / "failed_responses"
            / f"{spec.request_hash}_{response_sha}.json"
        )

    def _result(
        self,
        state: StateStore,
        config: BackfillConfig,
    ) -> AcquisitionRunResult:
        run = state.run(config.run_id)
        return AcquisitionRunResult(
            run_id=config.run_id,
            status=str(run["status"]),
            request_count=int(run["request_count"]),
            cache_hit_count=int(run["cache_hit_count"]),
            records_seen=int(run["records_seen"]),
            accepted_page_count=len(state.accepted_pages(config.run_id)),
            checkpoint_path=config.run_directory / "checkpoint.json",
        )

    def run(
        self,
        config: BackfillConfig,
        *,
        api_key: str,
        timeout_seconds: float = 30.0,
        max_network_attempts: int | None = None,
        required_cache_prefix_pages: int = 0,
    ) -> AcquisitionRunResult:
        """Execute or resume the approved bounded partition.

        ``config.max_requests`` remains the maximum page sequence in the
        immutable acquisition plan. ``max_network_attempts`` may impose a
        smaller cumulative HTTP-attempt ceiling for a cache-backed recovery
        run. This distinction lets an amended run traverse an already
        verified cache prefix without re-authorizing those historical calls.
        """
        network_attempt_ceiling = (
            config.max_requests
            if max_network_attempts is None
            else max_network_attempts
        )
        if not 1 <= network_attempt_ceiling <= config.max_requests:
            raise ValueError(
                "Network-attempt ceiling must be between 1 and "
                f"the page-slot ceiling ({config.max_requests})."
            )
        if not 0 <= required_cache_prefix_pages <= config.max_requests:
            raise ValueError(
                "Required cache-prefix pages must be between 0 and "
                f"the page-slot ceiling ({config.max_requests})."
            )
        cache = CacheStore(config.cache_directory)
        for sequence in range(1, required_cache_prefix_pages + 1):
            spec = request_spec(config, sequence)
            cached = cache.get(spec)
            if cached is None:
                raise CacheError(
                    "Required cache-prefix page is missing for sequence "
                    f"{sequence}."
                )
            record_count = response_record_count(cached.body)
            if record_count != cached.record_count:
                raise ResponseEnvelopeError(
                    "Required cache-prefix record count conflicts with "
                    "metadata."
                )
            if record_count != config.page_size:
                raise ResponseEnvelopeError(
                    "Required cache-prefix page must be full and "
                    f"nonterminal: sequence {sequence}."
                )
        with StateStore(config.state_path) as state:
            state.initialize_run(config, now=self.clock())
            run = state.run(config.run_id)
            if run["status"] == "complete":
                state.write_checkpoint(config)
                return self._result(state, config)

            sequence = int(run["next_sequence"])
            while sequence <= config.max_requests:
                spec = request_spec(config, sequence)
                cached = cache.get(spec)
                if cached is not None:
                    record_count = response_record_count(cached.body)
                    if record_count != cached.record_count:
                        raise ResponseEnvelopeError(
                            "Cached record count conflicts with metadata."
                        )
                    state.record_cache_hit(config.run_id, now=self.clock())
                    is_final = record_count < config.page_size
                    state.accept_page(
                        config.run_id,
                        spec,
                        source_kind="cache",
                        response_sha256=cached.response_sha256,
                        response_path=cached.response_path,
                        record_count=record_count,
                        is_final_page=is_final,
                        now=self.clock(),
                    )
                    state.write_checkpoint(config)
                    if is_final:
                        return self._result(state, config)
                    sequence += 1
                    continue

                run = state.run(config.run_id)
                if int(run["request_count"]) >= network_attempt_ceiling:
                    state.set_status(
                        config.run_id,
                        "budget_exhausted",
                        now=self.clock(),
                    )
                    state.write_checkpoint(config)
                    return self._result(state, config)

                wait_seconds = state.seconds_until_request_allowed(
                    now=self.clock(),
                    hourly_limit=config.hourly_request_limit,
                    minimum_interval_seconds=config.request_interval_seconds,
                )
                if wait_seconds:
                    self.sleeper(wait_seconds)

                attempted_at = self.clock()
                request_id = state.start_network_attempt(
                    config.run_id,
                    spec,
                    attempted_at=attempted_at,
                )
                try:
                    response = self.fetcher(
                        spec,
                        api_key,
                        timeout_seconds,
                    )
                except ApiRequestError as error:
                    state.finish_network_attempt(
                        request_id,
                        outcome="http_error",
                        http_status=error.status,
                        error_text=str(error),
                    )
                    state.set_status(
                        config.run_id,
                        "failed",
                        now=self.clock(),
                    )
                    state.write_checkpoint(config)
                    raise

                try:
                    record_count = response_record_count(response.body)
                except ResponseEnvelopeError as error:
                    failure_path = self._failure_path(
                        config,
                        spec,
                        response.body,
                    )
                    atomic_write(failure_path, response.body)
                    state.finish_network_attempt(
                        request_id,
                        outcome="invalid_response",
                        http_status=response.status,
                        response_sha256=sha256_bytes(response.body),
                        response_path=failure_path,
                        error_text=str(error),
                    )
                    state.set_status(
                        config.run_id,
                        "failed",
                        now=self.clock(),
                    )
                    state.write_checkpoint(config)
                    raise

                cached = cache.put_success(
                    spec,
                    body=response.body,
                    record_count=record_count,
                    response_metadata={
                        "status": response.status,
                        "content_type": response.content_type,
                        "content_encoding": response.content_encoding,
                    },
                    acquired_at_utc=attempted_at.astimezone(UTC).isoformat(),
                )
                state.finish_network_attempt(
                    request_id,
                    outcome="success",
                    http_status=response.status,
                    response_sha256=cached.response_sha256,
                    response_path=cached.response_path,
                    record_count=record_count,
                )
                is_final = record_count < config.page_size
                state.accept_page(
                    config.run_id,
                    spec,
                    source_kind="network",
                    response_sha256=cached.response_sha256,
                    response_path=cached.response_path,
                    record_count=record_count,
                    is_final_page=is_final,
                    now=self.clock(),
                )
                state.write_checkpoint(config)
                if is_final:
                    return self._result(state, config)
                sequence += 1

            state.set_status(
                config.run_id,
                "budget_exhausted",
                now=self.clock(),
            )
            state.write_checkpoint(config)
            return self._result(state, config)
