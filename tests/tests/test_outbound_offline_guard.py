"""Checks for the offline test tooling (network guard and import paths)."""

import socket

import pytest

from .offline import NetworkBlockedError, block_network  # noqa: F401

pytestmark = pytest.mark.usefixtures("block_network")


def test_socket_connect_is_blocked():
    """A raw socket connection attempt raises instead of connecting."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(NetworkBlockedError):
            sock.connect(("127.0.0.1", 9))
        with pytest.raises(NetworkBlockedError):
            sock.connect_ex(("127.0.0.1", 9))
    finally:
        sock.close()


def test_create_connection_is_blocked():
    """Higher level helpers built on ``socket.connect`` are blocked too."""
    with pytest.raises(NetworkBlockedError):
        socket.create_connection(("127.0.0.1", 9), timeout=1)


def test_conversions_imports_as_top_level_module():
    """``../server/settings`` is on the path, so ``conversions`` imports."""
    import conversions

    assert conversions.__name__ == "conversions"
