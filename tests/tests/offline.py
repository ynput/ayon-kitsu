"""Network guard for offline test modules.

Offline modules must run with no AYON server, no Kitsu server and no
network (Requirement 14.3). They import the fixture into their namespace
and apply it to every test of the module::

    import pytest

    from .offline import block_network  # noqa: F401

    pytestmark = pytest.mark.usefixtures("block_network")

Offline modules must not import ``tests/tests/fixtures.py``, which connects
to live servers at import time.
"""

import socket

import pytest


class NetworkBlockedError(RuntimeError):
    """Raised when an offline test tries to open a network connection.

    It is not an ``OSError`` on purpose, so HTTP clients that retry or
    swallow connection errors cannot hide an unexpected network call.
    """


def _blocked_connect(sock, address, *args, **kwargs):
    """Replacement for ``socket.socket.connect`` and ``connect_ex``.

    The socket is closed before raising, because callers such as
    ``socket.create_connection`` only close it on ``OSError``.

    Args:
        sock (socket.socket): The socket that tried to connect.
        address (Any): The address it tried to connect to.
        *args: Ignored positional arguments.
        **kwargs: Ignored keyword arguments.

    Raises:
        NetworkBlockedError: Always.
    """
    sock.close()
    raise NetworkBlockedError(
        f"Network access is blocked in offline tests (connect to {address!r})"
    )


@pytest.fixture
def block_network(monkeypatch):
    """Make every socket connection attempt raise for the test duration.

    ``socket.create_connection`` and all HTTP clients built on the standard
    socket module go through ``socket.socket.connect``, so they fail too.
    The original methods are restored after the test.

    Args:
        monkeypatch (pytest.MonkeyPatch): The pytest monkeypatch fixture.

    Yields:
        None: Control returns to the test while the network is blocked.
    """
    monkeypatch.setattr(socket.socket, "connect", _blocked_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", _blocked_connect)
    yield
