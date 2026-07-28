"""Immutable raw-response loading and integrity checks."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Iterable

from .models import RawApiDocument


class RawDataError(ValueError):
    """Raised when an immutable raw input cannot be accepted."""


def load_raw_document(path: Path) -> RawApiDocument:
    """Read one source file as immutable bytes and calculate its checksum."""
    resolved = path.resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"Raw Liquipedia response not found: {resolved}")

    content = resolved.read_bytes()
    if not content:
        raise RawDataError(f"Raw Liquipedia response is empty: {resolved}")
    return RawApiDocument(
        path=resolved,
        sha256=hashlib.sha256(content).hexdigest(),
        content=content,
    )


def load_raw_documents(paths: Iterable[Path]) -> tuple[RawApiDocument, ...]:
    """Load, deduplicate, and deterministically order saved responses."""
    documents_by_hash: dict[str, RawApiDocument] = {}
    for path in paths:
        document = load_raw_document(path)
        existing = documents_by_hash.get(document.sha256)
        if existing is None or document.path.as_posix() < existing.path.as_posix():
            documents_by_hash[document.sha256] = document

    if not documents_by_hash:
        raise RawDataError("At least one raw Liquipedia response is required.")
    return tuple(
        sorted(
            documents_by_hash.values(),
            key=lambda item: (item.sha256, item.path.as_posix()),
        )
    )
