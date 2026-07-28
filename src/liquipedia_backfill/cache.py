"""Immutable content-verified cache for successful historical API pages."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .planner import RequestSpec


class CacheError(ValueError):
    """Raised when a cached response fails integrity validation."""


def sha256_bytes(content: bytes) -> str:
    """Return the SHA-256 of response bytes."""
    return hashlib.sha256(content).hexdigest()


def atomic_write(path: Path, content: bytes) -> None:
    """Write bytes next to the target and publish with an atomic replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        dir=path.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as destination:
            destination.write(content)
            destination.flush()
            os.fsync(destination.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


@dataclass(frozen=True, slots=True)
class CachedPage:
    """One successful, immutable cached API response."""

    request_hash: str
    response_sha256: str
    response_path: Path
    metadata_path: Path
    body: bytes
    record_count: int


class CacheStore:
    """Store successful pages under their canonical request hash."""

    def __init__(self, root: Path):
        self.root = root.resolve()

    def page_directory(self, request_hash: str) -> Path:
        """Return the immutable directory for one request."""
        return self.root / request_hash

    def get(self, request: RequestSpec) -> CachedPage | None:
        """Return a verified successful cache entry when present."""
        directory = self.page_directory(request.request_hash)
        response_path = directory / "response.json"
        metadata_path = directory / "metadata.json"
        if not response_path.exists() and not metadata_path.exists():
            return None
        if not response_path.is_file() or not metadata_path.is_file():
            raise CacheError(f"Incomplete cache entry: {directory}")

        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if metadata.get("request_hash") != request.request_hash:
            raise CacheError(f"Request hash mismatch in cache: {directory}")
        body = response_path.read_bytes()
        response_sha256 = sha256_bytes(body)
        if metadata.get("response_sha256") != response_sha256:
            raise CacheError(f"Response checksum mismatch in cache: {directory}")
        return CachedPage(
            request_hash=request.request_hash,
            response_sha256=response_sha256,
            response_path=response_path,
            metadata_path=metadata_path,
            body=body,
            record_count=int(metadata["record_count"]),
        )

    def put_success(
        self,
        request: RequestSpec,
        *,
        body: bytes,
        record_count: int,
        response_metadata: dict[str, Any],
        acquired_at_utc: str,
    ) -> CachedPage:
        """Atomically store one validated HTTP 200 response."""
        existing = self.get(request)
        response_sha256 = sha256_bytes(body)
        if existing is not None:
            if existing.response_sha256 != response_sha256:
                raise CacheError(
                    "A successful cache entry already exists with different "
                    f"bytes for request {request.request_hash}."
                )
            return existing

        directory = self.page_directory(request.request_hash)
        directory.mkdir(parents=True, exist_ok=True)
        response_path = directory / "response.json"
        metadata_path = directory / "metadata.json"
        metadata = {
            "request_hash": request.request_hash,
            "request": request.canonical_payload,
            "url_without_credentials": request.url,
            "acquired_at_utc": acquired_at_utc,
            "http_status": int(response_metadata.get("status", 200)),
            "content_type": str(response_metadata.get("content_type", "")),
            "content_encoding": str(
                response_metadata.get("content_encoding", "")
            ),
            "response_sha256": response_sha256,
            "response_bytes": len(body),
            "record_count": record_count,
            "cache_state": "successful_validated_response",
        }
        atomic_write(response_path, body)
        atomic_write(
            metadata_path,
            (
                json.dumps(metadata, indent=2, sort_keys=True)
                + "\n"
            ).encode("utf-8"),
        )
        return self.get(request)  # type: ignore[return-value]
