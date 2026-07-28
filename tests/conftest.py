"""Repository-wide pytest safety policies."""

from __future__ import annotations

import socket
from collections.abc import Iterator
from typing import NoReturn

import pytest


def _network_disabled(*_args: object, **_kwargs: object) -> NoReturn:
    raise RuntimeError("Network access is disabled in the offline test suite")


@pytest.fixture(autouse=True)
def block_outbound_network(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Fail any test that attempts DNS resolution or an outbound socket."""

    monkeypatch.setattr(socket, "create_connection", _network_disabled)
    monkeypatch.setattr(socket, "getaddrinfo", _network_disabled)
    monkeypatch.setattr(socket.socket, "connect", _network_disabled)
    monkeypatch.setattr(socket.socket, "connect_ex", _network_disabled)
    monkeypatch.setattr(socket.socket, "sendto", _network_disabled)
    yield
