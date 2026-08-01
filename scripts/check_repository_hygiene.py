#!/usr/bin/env python3
"""Validate that Git contains source/evidence, not credentials or local state."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SELF = Path(__file__).resolve()

FORBIDDEN_PREFIXES = (
    ".secrets/",
    "data/backfill/plans/",
    "data/backfill/runs/",
    "data/processed/liquipedia/build_",
    "data/raw/liquipedia/",
    "data/training/dota_draft_supervised/build_",
    "data/validation/liquipedia/discovery/",
    "data/validation/liquipedia/runs/",
    "models/",
    "site/.next/",
    "site/.vinext/",
    "site/.wrangler/",
    "site/dist/",
    "site/node_modules/",
)
FORBIDDEN_PARTS = (
    "/__pycache__/",
    "/.pytest_cache/",
    "/node_modules/",
)
FORBIDDEN_SUFFIXES = (
    ".key",
    ".p12",
    ".pem",
    ".pfx",
    ".pyc",
    ".sqlite",
    ".sqlite3",
)
ALLOWED_ENV_FILES = {".env.example"}

SECRET_PATTERNS = {
    "private-key header": re.compile(
        rb"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"
    ),
    "AWS access key": re.compile(rb"\bAKIA[0-9A-Z]{16}\b"),
    "GitHub token": re.compile(rb"\bgh[pousr]_[A-Za-z0-9]{36,}\b"),
    "OpenAI-style secret": re.compile(rb"\bsk-[A-Za-z0-9_-]{20,}\b"),
    "concrete Liquipedia authorization": re.compile(
        rb"Authorization:\s*Apikey\s+[A-Za-z0-9_./+=-]{16,}",
        re.IGNORECASE,
    ),
}

IGNORE_PROBES = (
    ".secrets/liquipedia_api_key",
    ".env.local",
    "data/backfill/runs/example/state.sqlite3",
    "data/processed/liquipedia/build_example/manifest.json",
    "data/raw/liquipedia/backfill/example/response.json",
    "data/training/dota_draft_supervised/build_example/manifest.json",
    "data/validation/liquipedia/runs/example/response.json",
    "models/example.pkl",
    "site/.next/server/app.js",
    "site/.vinext/cache/example",
    "site/.wrangler/state/example",
    "site/dist/server/index.js",
    "site/node_modules/example/package.json",
)


def _git(*args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", *args],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
    )


def tracked_paths() -> tuple[str, ...]:
    result = _git("ls-files", "-z")
    if result.returncode != 0:
        raise RuntimeError(result.stderr.decode("utf-8", errors="replace"))
    return tuple(
        item.decode("utf-8", errors="strict")
        for item in result.stdout.split(b"\0")
        if item
    )


def forbidden_path_reason(relative_path: str) -> str | None:
    normalized = relative_path.replace("\\", "/")
    name = Path(normalized).name
    if normalized == ".env" or (
        name.startswith(".env") and normalized not in ALLOWED_ENV_FILES
    ):
        return "environment file"
    if normalized == ".DS_Store" or normalized.endswith("/.DS_Store"):
        return "operating-system metadata"
    if any(normalized.startswith(prefix) for prefix in FORBIDDEN_PREFIXES):
        return "credential, raw response, cache, generated build, or local state"
    if any(part in f"/{normalized}" for part in FORBIDDEN_PARTS):
        return "interpreter or test cache"
    if normalized.lower().endswith(FORBIDDEN_SUFFIXES):
        return "credential, bytecode, or local database"
    return None


def ignored_probe_failures() -> list[str]:
    failures: list[str] = []
    for probe in IGNORE_PROBES:
        result = _git("check-ignore", "--quiet", "--", probe)
        if result.returncode != 0:
            failures.append(probe)
    return failures


def secret_scan_failures(paths: tuple[str, ...]) -> list[tuple[str, str]]:
    failures: list[tuple[str, str]] = []
    for relative_path in paths:
        candidate = PROJECT_ROOT / relative_path
        if candidate.resolve() == SELF or not candidate.is_file():
            continue
        try:
            content = candidate.read_bytes()
        except OSError:
            failures.append((relative_path, "unreadable tracked file"))
            continue
        if b"\0" in content:
            continue
        for label, pattern in SECRET_PATTERNS.items():
            if pattern.search(content):
                failures.append((relative_path, label))
    return failures


def main() -> int:
    try:
        paths = tracked_paths()
    except RuntimeError as error:
        print(f"repository hygiene check failed: {error}", file=sys.stderr)
        return 2

    path_failures = [
        (relative_path, reason)
        for relative_path in paths
        if (reason := forbidden_path_reason(relative_path)) is not None
    ]
    ignore_failures = ignored_probe_failures()
    secret_failures = secret_scan_failures(paths)

    if not path_failures and not ignore_failures and not secret_failures:
        print(
            "Repository hygiene passed: tracked paths, ignore rules, "
            "and high-confidence secret signatures are clean."
        )
        return 0

    print("Repository hygiene failed.", file=sys.stderr)
    for relative_path, reason in path_failures:
        print(f"- forbidden tracked path: {relative_path} ({reason})", file=sys.stderr)
    for probe in ignore_failures:
        print(f"- required local path is not ignored: {probe}", file=sys.stderr)
    for relative_path, label in secret_failures:
        print(
            f"- high-confidence secret signature: {relative_path} ({label})",
            file=sys.stderr,
        )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
