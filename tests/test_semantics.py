"""Language handling and fallbacks.

These are the paths that failed silently in practice: a wrong answer with a 200
status rather than an exception.
"""

import pytest
import sdmx

from conftest import parse, raw
from macro_mcp import bundesbank as bbk
from macro_mcp import sdmx_api as api


class Name:
    def __init__(self, loc):
        self.localizations = loc


class Obj:
    def __init__(self, loc, ident="X"):
        self.id, self.name = ident, Name(loc)


def test_names_drops_null_localizations():
    assert api._names(Obj({"en": None, "de": "Bilanz"})) == {"de": "Bilanz"}


def test_label_prefers_english_but_falls_back():
    assert api._label({"en": "Crops", "it": "Coltivazioni"}) == "Crops"
    assert api._label({"it": "Coltivazioni"}) == "Coltivazioni"
    assert api._label({}) == ""


def test_null_english_name_does_not_mask_the_german_one():
    """BBK publishes a null en name on some flows; it used to win over the real
    German label and crash search on None.lower()."""
    names = api._names(Obj({"en": None, "de": "Gewinn- und Verlustrechnung"}))
    assert api._label(names) == "Gewinn- und Verlustrechnung"
    assert api._matches("gewinn", "BBKRT", names)


def test_search_matches_across_localizations():
    names = {"en": "Crops", "it": "Coltivazioni"}
    assert api._matches("crops", "101_1015", names)
    assert api._matches("coltivazioni", "101_1015", names)
    assert api._matches("101", "101_1015", names)
    assert not api._matches("unemployment", "101_1015", names)


def test_bbk_dataflow_fixture_contains_a_null_english_name():
    """Pins the real-world case the fallback exists for."""
    flows = parse(bbk._repair(raw("bbk_dataflow.xml"))).dataflow
    nulls = {k: api._names(v) for k, v in flows.items()
             if (getattr(v.name, "localizations", None) or {}).get("en") is None}
    assert nulls, "fixture should still contain a flow with a null English name"
    assert all(api._label(n) for n in nulls.values()), "each must fall back to a real label"


def test_codes_falls_back_when_inline_codelist_is_empty(monkeypatch):
    sentinel = ["fetched"]
    monkeypatch.setattr(bbk, "codelist", lambda dim_id: sentinel)

    class Rep:
        enumerated = []          # present but empty, as BBK serves it

    class Dim:
        id, local_representation = "BBK_STD_FREQ", Rep()

    assert api._codes(Dim(), "BBK") is sentinel
    assert api._codes(Dim(), "ECB") == []      # other providers keep the empty list


def test_english_label_coverage_is_reported_only_when_incomplete(monkeypatch):
    codes = [Obj({"it": "Italia"}, "IT"), Obj({"en": "Germany"}, "DE")]

    class Dim:
        id = "GEO"

    class DSD:
        class dimensions:
            components = [Dim()]

    monkeypatch.setattr(api, "_dsd", lambda p, f: DSD)
    monkeypatch.setattr(api, "_supports", lambda p, r: True)

    monkeypatch.setattr(api, "_codes", lambda d, p=None: codes)
    partial = api.describe_flow("X", "F")["dimensions"][0]
    assert partial["english_labels"] == "1/2"
    assert partial["languages"] == ["en", "it"]

    monkeypatch.setattr(api, "_codes", lambda d, p=None: [Obj({"en": "Germany"}, "DE")])
    complete = api.describe_flow("X", "F")["dimensions"][0]
    assert "english_labels" not in complete


def test_fetch_retries_with_generic_sdmx_when_parsing_fails(monkeypatch):
    """BIS serves structure-specific data referencing a DSD sdmx1 cannot resolve."""
    calls = []

    class Client:
        def data(self, flow, key, params, headers=None):
            calls.append(headers)
            if headers is None:
                raise sdmx.exceptions.XMLParseError
            return "message"

    monkeypatch.setattr(api, "_client", lambda p: Client())
    monkeypatch.setattr(api.sdmx, "to_pandas", lambda m: _frame())

    out = api.fetch("BIS", "WS_CBPOL", {"FREQ": "M"})
    assert out["total"] == 1
    assert len(calls) == 2
    assert "genericdata" in calls[1]["Accept"]


def _frame():
    import pandas as pd
    return pd.Series([1.0], index=pd.Index(["2024-01"], name="TIME_PERIOD"))
