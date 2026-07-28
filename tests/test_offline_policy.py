"""Tests for repository-level offline and hygiene guarantees."""

from __future__ import annotations

import socket
import subprocess
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_outbound_network_is_blocked() -> None:
    with pytest.raises(RuntimeError, match="Network access is disabled"):
        socket.create_connection(("example.invalid", 443))


def test_repository_hygiene_check_passes() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/check_repository_hygiene.py"],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
