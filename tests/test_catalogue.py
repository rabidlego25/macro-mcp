"""The cross-provider index: which provider carries a subject.

`find_dataflows` searches one provider, and an eval asked IMF for unemployment,
got `total: 0`, and had no way to learn that ILO has 108 flows for it. Reading
20 catalogues live is 63s of Eurostat and 51s of ISTAT on a cold cache, so the
index is built once by `scripts.catalogue` and shipped.

The index is a routing hint: what it says is confirmed with a real call, so
these tests are about what it says and never about a number it holds.
"""

import gzip
import json

import pytest

from macro_mcp import hkma
from macro_mcp import sdmx_api as api

# Small enough to reason about, shaped like the real thing: one provider with
# the exact name, one with many loose matches, one with none.
INDEX = {
    "built": "2026-01-01",
    "providers": {
        "ILO": [["DF_UNE_A", "Unemployment rate by sex and age"],
                ["DF_UNE_B", "Unemployment by sex and education"],
                ["DF_EMP_A", "Employment by sex"]],
        "ISTAT": [["151_929", "Unemployment", "Disoccupazione"]],
        "ECB": [["EXR", "Exchange Rates"]],
    },
}


@pytest.fixture
def index(monkeypatch):
    monkeypatch.setattr(api, "_catalogue", lambda: INDEX)
    return INDEX


def test_searching_every_provider_needs_a_term(index):
    """40,000 flow names is not an answer to anything."""
    assert "error" in api.dataflows("*")


def test_it_says_which_providers_carry_a_subject(index):
    got = api.dataflows("*", "unemployment")
    assert [p["provider"] for p in got["providers"]] == ["ISTAT", "ILO"]
    assert got["total"] == 3
    assert [p["flows"] for p in got["providers"]] == [1, 2]


def test_providers_are_ordered_by_their_best_hit_not_their_count(index):
    """ISTAT has one flow named exactly "Unemployment" and ILO has two that are
    about it. Ordering by count would call 500 loose matches a better answer
    than the flow somebody asked for."""
    assert api.dataflows("*", "unemployment")["providers"][0]["provider"] == "ISTAT"


def test_each_provider_carries_its_region(index):
    """The difference between the two hits a routing question chooses between:
    ILO covers 190 countries and ISTAT covers Italy."""
    by = {p["provider"]: p["region"] for p in api.dataflows("*", "unemployment")["providers"]}
    assert by == {"ILO": "international", "ISTAT": "national_eu"}


def test_it_matches_localizations_like_the_live_search(index):
    got = api.dataflows("*", "disoccupazione")
    assert [p["provider"] for p in got["providers"]] == ["ISTAT"]


def test_the_answer_says_it_is_an_index_and_when_it_was_built(index):
    """It can be out of date, and a response that hid that would be inviting
    the agent to trust an id the provider has since retired."""
    got = api.dataflows("*", "unemployment")
    assert got["index_built"] == "2026-01-01"
    assert "confirm" in got["note"]


def test_a_zero_names_the_providers_that_do_have_it(spine, index):
    """The eval's exact dead end. ECB has no unemployment flow, and the useful
    half of that response is the part that was missing."""
    got = api.dataflows("ECB", "unemployment")
    assert got["total"] == 0
    assert [e["provider"] for e in got["elsewhere"]] == ["ISTAT", "ILO"]
    assert "elsewhere" in got["note"]


def test_a_search_that_found_something_is_left_alone(spine, index):
    got = api.dataflows("ECB", "exchange")
    assert got["total"] and "elsewhere" not in got


def test_hong_kong_is_folded_in_from_the_live_table_not_the_file():
    """Its catalogue already ships in hkma.py. Building it into the index too
    would be two copies to keep in step."""
    got = api._catalogue()["providers"]["HKMA"]
    assert len(got) == len(hkma.FLOWS)
    assert ["hk-interbank-ir-daily", "hk interbank ir daily"] in got


def test_a_missing_index_degrades_rather_than_breaks(spine, monkeypatch):
    """A checkout with no index built still searches one provider at a time,
    which is where this started."""
    monkeypatch.setattr(api, "CATALOGUE", api.CATALOGUE.with_name("absent.json.gz"))
    api._catalogue.cache_clear()
    assert "error" in api.dataflows("*", "unemployment")
    assert "elsewhere" not in api.dataflows("ECB", "unemployment")
    api._catalogue.cache_clear()


def test_the_index_is_actually_shipped():
    """The whole feature is one data file, and it degrades silently without it.
    A packaging change that dropped it would break nothing else in this suite."""
    built = json.loads(gzip.decompress(api.CATALOGUE.read_bytes()))
    assert built["built"] and len(built["providers"]) > 10
    assert sum(len(f) for f in built["providers"].values()) > 20000
    for provider, flows in built["providers"].items():
        assert provider in api.GROUPS[api._region(provider)]
        assert all(len(f) >= 2 and f[0] and f[1] for f in flows[:50]), provider
