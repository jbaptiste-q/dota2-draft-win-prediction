"""Step 2: fetch and locally cache Dota 2 patch note payloads.

This is one of the two network-touching modules in Milestone 9 Phase 1
(the other is hero_mapping.py). Both are deliberately kept out of
tests/ -- tests/conftest.py's autouse block_outbound_network fixture
would hard-fail any test that imported and called them, and importing
alone (with no call) proves nothing about real API behavior, so no
test doubles are written for this phase.

Raw patch note JSON is Valve's content and is never committed -- only
the fetch manifest (URL, timestamp, byte count, SHA-256 per version) is.
The write/hash conventions here mirror src/liquipedia_backfill/cache.py
(atomic tempfile-then-replace writes, sha256_bytes, sorted-key indented
JSON with a trailing newline) without importing from it, since this
module targets an unrelated, unauthenticated public API and must stay
fully independent of the Liquipedia acquisition path.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


USER_AGENT = "Dota2AIPortfolioPatchAlignment/1.0"
PATCH_NOTES_URL = "https://www.dota2.com/datafeed/patchnotes"
PATCH_NOTES_LIST_URL = "https://www.dota2.com/datafeed/patchnoteslist"
DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_POLITE_DELAY_SECONDS = 1.5
MANIFEST_SCHEMA_VERSION = "dota2-ml-portfolio-patch-notes-manifest-v1"
REQUIRED_PATCH_NOTES_KEYS = (
    "patch_name",
    "patch_timestamp",
    "heroes",
)
OPTIONAL_PATCH_NOTES_KEYS = (
    "items",
    "neutral_items",
    "neutral_creeps",
    "general_notes",
)
DEFAULT_RAW_DIRECTORY = Path("data/raw/patch_notes")
DEFAULT_MANIFEST_PATH = DEFAULT_RAW_DIRECTORY / "manifest.json"


class PatchNotesFetchError(RuntimeError):
    """Raised when one patch-note request fails or has an unexpected shape."""


@dataclass(frozen=True, slots=True)
class FetchedPatchNotes:
    """One successfully fetched and locally stored patch-note payload."""

    version: str
    url: str
    fetched_at_utc: str
    byte_count: int
    sha256: str
    raw_path: Path


@dataclass(frozen=True, slots=True)
class PatchNotesFetchFailure:
    """One requested version that could not be fetched or verified."""

    version: str
    url: str
    reason: str


def sha256_bytes(content: bytes) -> str:
    """Return the SHA-256 of response bytes."""

    return hashlib.sha256(content).hexdigest()


def _atomic_write(path: Path, content: bytes) -> None:
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


def _get(url: str, *, timeout_seconds: float) -> bytes:
    request = Request(
        url,
        method="GET",
        headers={
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        },
    )
    with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310
        return response.read()


def fetch_patch_notes_list(
    *, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
) -> dict[str, object]:
    """Fetch the full version list: patch_number, patch_name, patch_timestamp."""

    url = f"{PATCH_NOTES_LIST_URL}?language=english"
    body = _get(url, timeout_seconds=timeout_seconds)
    payload = json.loads(body)
    if not isinstance(payload, dict) or not isinstance(
        payload.get("patches"), list
    ):
        raise PatchNotesFetchError(
            "Patch notes list response did not contain a 'patches' array."
        )
    return payload


def _validate_patch_notes_shape(payload: object, *, version: str) -> None:
    if not isinstance(payload, dict):
        raise PatchNotesFetchError(f"{version}: response is not a JSON object.")
    if payload.get("success") is not True:
        raise PatchNotesFetchError(
            f"{version}: response did not report success=true "
            f"(got {payload.get('success')!r})."
        )
    if payload.get("patch_number") != version:
        raise PatchNotesFetchError(
            f"{version}: response patch_number "
            f"{payload.get('patch_number')!r} does not match the requested "
            "version -- refusing to substitute."
        )
    missing = [key for key in REQUIRED_PATCH_NOTES_KEYS if key not in payload]
    if missing:
        raise PatchNotesFetchError(
            f"{version}: response is missing expected keys: {missing}."
        )


def fetch_one_version(
    version: str,
    *,
    output_directory: Path,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> FetchedPatchNotes:
    """Fetch, shape-validate, and locally store one version's raw patch notes."""

    url = f"{PATCH_NOTES_URL}?version={version}&language=english"
    body = _get(url, timeout_seconds=timeout_seconds)
    payload = json.loads(body)
    _validate_patch_notes_shape(payload, version=version)

    fetched_at_utc = datetime.now(UTC).isoformat()
    raw_path = output_directory / f"{version}.json"
    _atomic_write(raw_path, body)
    return FetchedPatchNotes(
        version=version,
        url=url,
        fetched_at_utc=fetched_at_utc,
        byte_count=len(body),
        sha256=sha256_bytes(body),
        raw_path=raw_path,
    )


def fetch_versions(
    versions: Sequence[str],
    *,
    output_directory: Path = DEFAULT_RAW_DIRECTORY,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    polite_delay_seconds: float = DEFAULT_POLITE_DELAY_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[list[FetchedPatchNotes], list[PatchNotesFetchFailure]]:
    """Fetch every listed version, one at a time, politely rate-limited.

    A failure on one version never raises or aborts the batch -- it is
    collected and returned alongside the successes so the caller can
    report exactly which versions returned no data or an unexpected
    shape, without ever substituting a nearby version.
    """

    successes: list[FetchedPatchNotes] = []
    failures: list[PatchNotesFetchFailure] = []
    for index, version in enumerate(versions):
        if index > 0:
            sleep(polite_delay_seconds)
        url = f"{PATCH_NOTES_URL}?version={version}&language=english"
        try:
            successes.append(
                fetch_one_version(
                    version,
                    output_directory=output_directory,
                    timeout_seconds=timeout_seconds,
                )
            )
        except (
            HTTPError,
            URLError,
            TimeoutError,
            json.JSONDecodeError,
            PatchNotesFetchError,
        ) as error:
            failures.append(
                PatchNotesFetchFailure(
                    version=version,
                    url=url,
                    reason=str(error),
                )
            )
    return successes, failures


def write_manifest(
    *,
    manifest_path: Path,
    successes: Sequence[FetchedPatchNotes],
    failures: Sequence[PatchNotesFetchFailure],
    generated_at_utc: str,
) -> None:
    """Write the committed provenance manifest for one fetch run."""

    payload = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "generated_at_utc": generated_at_utc,
        "source_endpoint": f"{PATCH_NOTES_URL}?version={{version}}&language=english",
        "versions": [
            {
                "version": item.version,
                "url": item.url,
                "fetched_at_utc": item.fetched_at_utc,
                "byte_count": item.byte_count,
                "sha256": item.sha256,
                "raw_file": item.raw_path.name,
            }
            for item in sorted(successes, key=lambda item: item.version)
        ],
        "failures": [
            {
                "version": failure.version,
                "url": failure.url,
                "reason": failure.reason,
            }
            for failure in sorted(failures, key=lambda failure: failure.version)
        ],
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


__all__ = [
    "DEFAULT_MANIFEST_PATH",
    "DEFAULT_RAW_DIRECTORY",
    "FetchedPatchNotes",
    "OPTIONAL_PATCH_NOTES_KEYS",
    "PatchNotesFetchError",
    "PatchNotesFetchFailure",
    "REQUIRED_PATCH_NOTES_KEYS",
    "fetch_one_version",
    "fetch_patch_notes_list",
    "fetch_versions",
    "sha256_bytes",
    "write_manifest",
]
