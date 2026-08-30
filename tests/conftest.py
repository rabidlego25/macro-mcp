import gzip
import io
import pathlib
from functools import lru_cache

import pytest
import requests
import sdmx
from requests.adapters import HTTPAdapter
from sdmx.session import Session

from macro_mcp import bundesbank, cache
from macro_mcp import sdmx_api as api

FIXTURES = pathlib.Path(__file__).parent / "fixtures"

MEMOISED = (cache.session, api._client, api._flows, api._dsd, api._unit_labels,
            api._dim_labels,
            bundesbank.flows, bundesbank.dsd, bundesbank.codelist)


def raw(name: str) -> bytes:
    """A recorded response, decompressed if it was stored that way.

    ECB's EXR structure is 497KB because it carries the whole currency
    codelist, and it gzips to a tenth of that. Trimming it by hand would make
    it something other than a response the service actually sent, which is the
    only reason to keep it at all.
    """
    payload = (FIXTURES / name).read_bytes()
    return gzip.decompress(payload) if name.endswith(".gz") else payload


def parse(payload: bytes):
    return sdmx.read_sdmx(io.BytesIO(payload))


LEARNED = (api._NEEDS_GENERIC, api._NO_LAST_N)


@pytest.fixture(autouse=True)
def unlearned():
    """Which providers need the generic Accept header, and which will not take a
    download cap, are learned at runtime and kept for the life of the process,
    so both have to be forgotten between tests."""
    for known in LEARNED:
        known.clear()
    yield
    for known in LEARNED:
        known.clear()


@pytest.fixture
def load():
    return raw


class Replay(HTTPAdapter):
    """Answers requests from recorded responses, matched on the URL.

    Mounted under a real sdmx1 Session, so a test drives the whole spine — URL
    construction, the Accept header, sdmx1's parser and this module's code —
    against payloads the services actually sent. Stubbing `_client` instead
    exercises none of that, and the URL is where several of the live failures
    were.

    An unrecognised URL is a failure rather than a blank response: a spine test
    that quietly made no request would pass on nothing at all.
    """

    def __init__(self, routes):
        self.routes = routes
        self.asked = []
        super().__init__()

    @property
    def urls(self) -> list[str]:
        return [r.url for r in self.asked]

    def accepts(self) -> list[str]:
        return [r.headers.get("Accept", "") for r in self.asked]

    def send(self, request, **kwargs):
        self.asked.append(request)
        for fragment, route in self.routes.items():
            if fragment in request.url:
                # A route may depend on the request, because a service may:
                # BIS answers the same URL with a different payload according
                # to the Accept header, which is the whole subject of one of
                # these tests.
                name, content_type, *rest = (route(request) if callable(route)
                                             else route)
                r = requests.Response()
                r.status_code = rest[0] if rest else 200
                r.url = request.url
                r.request = request
                r._content = raw(name)
                if content_type:
                    r.headers["Content-Type"] = content_type
                return r
        raise AssertionError(f"no response recorded for {request.url}")


# As the services send them: sdmx1 picks its reader from this and refuses a
# response without one, so a fixture served under the wrong type is not the
# response that was recorded.
STRUCTURE = "application/vnd.sdmx.structure+xml;version=2.1"
GENERIC_DATA = "application/vnd.sdmx.genericdata+xml;version=2.1"
BIS_XML = "application/xml;charset=UTF-8"  # BIS labels every response this way

# ECB is the spine: standard SDMX 2.1 over sdmx1's own URL builder, which is
# the path 27 of the 29 providers take. The three exceptions have fixtures of
# their own.
ECB_ROUTES = {
    "/dataflow/ECB/all": ("ecb_dataflow.xml", STRUCTURE),
    "/dataflow/ECB/EXR": ("ecb_dsd.xml.gz", STRUCTURE),
    "/data/EXR/": ("ecb_data.xml", GENERIC_DATA),
}

# BIS serves structure-specific data referencing a DSD sdmx1 cannot resolve, so
# the default request fails to parse and the generic Accept header is what
# works. Both payloads are recorded, keyed off the header the way the service
# keys off it.
BIS_ROUTES = {
    "/dataflow/BIS/WS_CBPOL": ("bis_dsd.xml.gz", BIS_XML),
    "/data/WS_CBPOL/": lambda request: (
        ("bis_data_generic.xml", BIS_XML)
        if "genericdata" in request.headers.get("Accept", "")
        else ("bis_data_structurespecific.xml", BIS_XML)),
}


JSON_API = "application/vnd.api+json"
TOYOTA = "5493006W3QUS5LMH6R84"
TOYOTA_CHILD = "254900OR20P23DBVOT48"

# GLEIF answers a missing relationship with 404 and a JSON:API error document,
# not with an empty one, so the absence of a parent is an exception to catch
# rather than a field to read. The sub-resource routes come first: the record
# fragment is a prefix of all of them.
GLEIF_ROUTES = {
    f"{TOYOTA}/direct-parent": ("gleif_not_found.json", JSON_API, 404),
    f"{TOYOTA}/ultimate-parent": ("gleif_not_found.json", JSON_API, 404),
    f"{TOYOTA}/direct-children": ("gleif_children.json", JSON_API),
    f"{TOYOTA_CHILD}/direct-parent": ("gleif_record.json", JSON_API),
    f"{TOYOTA_CHILD}/ultimate-parent": ("gleif_record.json", JSON_API),
    f"{TOYOTA_CHILD}/direct-children": ("gleif_not_found.json", JSON_API, 404),
    f"lei-records/{TOYOTA}": ("gleif_record.json", JSON_API),
    "lei-records?": ("gleif_search.json", JSON_API),
}


def forget():
    """Drop every memoised response, including sdmx1's own.

    `sdmx.Client.cache` is a class attribute, so it is shared by every client in
    the process and outlives any instance this module makes. Clearing only the
    lru_caches here leaves structures answered from a dict nothing else can
    see — which is how a measurement of two runs came out as a saving that was
    really the second run reading the first one's downloads.
    """
    for fn in MEMOISED:
        fn.cache_clear()
    sdmx.Client.cache.clear()


def replay(monkeypatch, routes) -> Replay:
    """Point every provider request at `routes` for the length of a test."""
    forget()
    adapter = Replay(routes)
    session = Session(timeout=cache.TIMEOUT)
    session.headers["User-Agent"] = cache.USER_AGENT
    for prefix in ("http://", "https://"):
        session.mount(prefix, adapter)
    monkeypatch.setattr(cache, "session", lru_cache(maxsize=1)(lambda: session))
    return adapter


@pytest.fixture
def spine(monkeypatch):
    """The generic SDMX path, served from recorded ECB responses."""
    adapter = replay(monkeypatch, ECB_ROUTES)
    yield adapter
    forget()


@pytest.fixture
def uncached(monkeypatch):
    """Force a real network round trip.

    Both layers have to go: the disk cache, and the in-process memoisation
    that would otherwise answer before the session is ever consulted.
    """
    monkeypatch.setenv("MACRO_MCP_NO_CACHE", "1")
    forget()
    yield
    forget()
