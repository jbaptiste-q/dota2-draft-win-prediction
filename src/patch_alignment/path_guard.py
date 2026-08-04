"""Refuse to write Valve's raw patch-note text anywhere git could commit it.

Shared by any script that joins labels back to raw_text for local human
review (build_review_sheet.py, the Step 2A experiment script).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class RefusedWritePathError(RuntimeError):
    """Raised when the requested output path is not covered by .gitignore."""


def assert_path_is_gitignored(path: Path) -> None:
    """Raise RefusedWritePathError unless `git check-ignore` confirms path is ignored."""

    result = subprocess.run(
        ["git", "check-ignore", "--quiet", str(path)],
        cwd=PROJECT_ROOT,
        check=False,
    )
    if result.returncode != 0:
        raise RefusedWritePathError(
            f"{path} is not covered by .gitignore. Refusing to write raw "
            "patch-note text (Valve's content) to a path that could be committed."
        )


__all__ = ["PROJECT_ROOT", "RefusedWritePathError", "assert_path_is_gitignored"]
