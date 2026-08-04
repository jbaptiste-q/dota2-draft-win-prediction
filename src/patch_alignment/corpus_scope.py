"""Step 1: the exact scope of patch versions to align (read-only, offline).

This module only reads the already-validated, hash-verified M4A working
corpus through the existing draft_ai_modeling loader. It performs no
network access and modifies nothing; it exists purely to answer "which
patch versions were actually observed, and how many games each has"
before Milestone 9 fetches anything.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from src.draft_ai_modeling.loader import load_working_corpus


DEFAULT_CORPUS_CONFIG_PATH = Path("configs/modeling/m4a_working_corpus.json")
PATCH_COLUMN = "patch"


@dataclass(frozen=True, slots=True)
class ObservedPatchVersion:
    """One distinct, non-null patch value and its row count."""

    patch: str
    games: int


@dataclass(frozen=True, slots=True)
class CorpusPatchScope:
    """The exact Milestone 9 alignment scope: every observed patch version."""

    total_rows: int
    missing_patch_rows: int
    versions: tuple[ObservedPatchVersion, ...]

    @property
    def version_strings(self) -> tuple[str, ...]:
        """Every distinct patch value, in the same order as ``versions``."""

        return tuple(item.patch for item in self.versions)

    @property
    def covered_rows(self) -> int:
        return sum(item.games for item in self.versions)


def observed_patch_scope(
    corpus_config_path: Path = DEFAULT_CORPUS_CONFIG_PATH,
    *,
    repository_root: Path | None = None,
) -> CorpusPatchScope:
    """Return every distinct non-null patch value observed in the corpus.

    Versions are ordered the same way the semantic patch numbers sort
    (ascending, matching how M4B.3's patch diagnostics already group and
    report them), not by frequency.
    """

    corpus = load_working_corpus(
        corpus_config_path,
        repository_root=repository_root,
    )
    frame = corpus.frame
    if PATCH_COLUMN not in frame.columns:
        raise KeyError(
            f"The working corpus is missing the {PATCH_COLUMN!r} column."
        )

    patch_series = frame[PATCH_COLUMN]
    missing_rows = int(patch_series.isna().sum())
    counts = patch_series.dropna().value_counts()

    versions = tuple(
        ObservedPatchVersion(patch=str(patch), games=int(counts[patch]))
        for patch in sorted(counts.index, key=_patch_sort_key)
    )
    return CorpusPatchScope(
        total_rows=len(frame),
        missing_patch_rows=missing_rows,
        versions=versions,
    )


def _patch_sort_key(patch: str) -> tuple[object, ...]:
    """Sort patch strings like ``7.9`` < ``7.10`` < ``7.10b``, not lexically.

    Splits the numeric major.minor prefix from any trailing letter suffix
    (e.g. ``"7.39e"`` -> ``(7, 39, "e")``), falling back to a plain string
    key for anything that does not match the usual ``M.mm[letter]`` shape
    so an unexpected value never raises here — it just sorts last among
    its peers instead of crashing this offline, read-only report.
    """

    text = str(patch)
    major_minor = ""
    index = 0
    for index, character in enumerate(text):
        if character.isdigit() or character == ".":
            major_minor += character
        else:
            break
    else:
        index = len(text)
    suffix = text[index:]
    parts = major_minor.split(".")
    try:
        numeric = tuple(int(part) for part in parts if part != "")
    except ValueError:
        return (1, text)
    if not numeric:
        return (1, text)
    return (0, numeric, suffix)


__all__ = [
    "CorpusPatchScope",
    "DEFAULT_CORPUS_CONFIG_PATH",
    "ObservedPatchVersion",
    "observed_patch_scope",
]
