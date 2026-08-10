"""Bundesbank adapter.

BBK serves standard SDMX-ML 2.1, but sdmx1 cannot talk to it for two reasons:
metadata lives at /rest/metadata/<resource>/BBK instead of the usual
/rest/<resource>/BBK/all/latest, and data responses carry valueless attribute
elements its reader raises on. Both are handled here.
"""

import io
import re
from functools import lru_cache

import requests
import sdmx

from . import cache

BASE = "https://api.statistiken.bundesbank.de/rest"

# <generic:Value id="BBK_UNIT_ENG"></generic:Value> — an attribute element with
# no value=, which sdmx1 reads as KeyError: 'value'.
_VALUELESS = re.compile(rb'<(\w+:)?Value\s+id="[^"]*"\s*>\s*</(\w+:)?Value>')

# BBK writes urn:...infomodel.codelist=BBK:X, dropping the class segment that
# makes it a valid SDMX URN.
_URN_CLASS = {b"codelist": b"Codelist", b"conceptscheme": b"ConceptScheme",
              b"categoryscheme": b"CategoryScheme"}
_URN = re.compile(rb"infomodel\.(" + b"|".join(_URN_CLASS) + rb")=")


def _repair(raw: bytes) -> bytes:
    fixed = _URN.sub(lambda m: b"infomodel.%s.%s=" % (m[1], _URN_CLASS[m[1]]), raw)
    return _VALUELESS.sub(b"", fixed)


def _get(path: str, params: dict | None = None):
    # sdmx.Session keeps `timeout` for its own Client to read, so a bare get()
    # would otherwise have none.
    r = cache.session().get(f"{BASE}/{path}", params=params or {},
                            timeout=cache.TIMEOUT)
    r.raise_for_status()
    return sdmx.read_sdmx(io.BytesIO(_repair(r.content)))


@lru_cache(maxsize=1)
def flows():
    return _get("metadata/dataflow/BBK").dataflow


@lru_cache(maxsize=32)
def dsd(flow: str):
    sid = flows()[flow].structure.id
    return _get(f"metadata/datastructure/BBK/{sid}").structure[sid]


@lru_cache(maxsize=64)
def codelist(dim_id: str):
    """Dimension codelists are not embedded in the DSD; they are separate
    resources named CL_<dimension>."""
    try:
        return _get(f"metadata/codelist/BBK/CL_{dim_id}").codelist[f"CL_{dim_id}"]
    except requests.HTTPError:
        return None


def dimensions(flow: str) -> list[str]:
    return [d.id for d in dsd(flow).dimensions.components if d.id != "TIME_PERIOD"]


def data(flow: str, key: dict, params: dict):
    """Key positions are dot-separated in dimension order; blanks wildcard.

    An unconstrained query returns well over 100MB, so at least one dimension
    must be pinned.
    """
    dims = dimensions(flow)
    if not any(key.get(d) for d in dims):
        raise ValueError(
            f"{flow} needs at least one of {dims} pinned; an open query returns "
            "more than 100MB")
    return _get(f"data/{flow}/" + ".".join(str(key.get(d, "")) for d in dims), params)
