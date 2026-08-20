import io
import pathlib

import pytest
import sdmx

from macro_mcp import bundesbank, cache
from macro_mcp import sdmx_api as api

FIXTURES = pathlib.Path(__file__).parent / "fixtures"

MEMOISED = (cache.session, api._client, api._flows, api._dsd,
            bundesbank.flows, bundesbank.dsd, bundesbank.codelist)


def raw(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def parse(payload: bytes):
    return sdmx.read_sdmx(io.BytesIO(payload))


@pytest.fixture(autouse=True)
def unlearned():
    """Which providers need the generic Accept header is learned at runtime and
    kept for the life of the process, so it has to be forgotten between tests."""
    api._NEEDS_GENERIC.clear()
    yield
    api._NEEDS_GENERIC.clear()


@pytest.fixture
def load():
    return raw


@pytest.fixture
def uncached(monkeypatch):
    """Force a real network round trip.

    Both layers have to go: the disk cache, and the in-process memoisation
    that would otherwise answer before the session is ever consulted.
    """
    monkeypatch.setenv("MACRO_MCP_NO_CACHE", "1")
    for fn in MEMOISED:
        fn.cache_clear()
    yield
    for fn in MEMOISED:
        fn.cache_clear()
