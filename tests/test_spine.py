"""The SDMX spine, driven offline from responses the services actually sent.

Twenty-seven of the twenty-nine providers reach the agent through this one
path: sdmx1 builds the URL, the provider answers, and this module turns the
message into the response shape. Everything recorded before this file covered
Bundesbank, Hong Kong and Singapore — the three adapters that are exceptions to
the spine — so the spine itself was tested either against the live services or
against stubs that skipped the parts most likely to be wrong.

The fixtures are mounted under a real sdmx1 Session, so these exercise URL
construction, the Accept header, sdmx1's parser and the packing here, together.
"""

import pytest
import sdmx

from conftest import BIS_ROUTES, BIS_XML, replay
from macro_mcp import sdmx_api as api

JPY = {"FREQ": "D", "CURRENCY": "JPY", "CURRENCY_DENOM": "EUR",
       "EXR_TYPE": "SP00", "EXR_SUFFIX": "A"}


# --- discovery ---------------------------------------------------------------

def test_the_dataflow_list_is_searched_by_id_and_by_name(spine):
    """ECB publishes 104 flows; "exchange" is a word in three of their names and
    in none of their ids."""
    assert api.dataflows("ECB")["total"] == 104

    found = api.dataflows("ECB", "exchange", 40)
    assert found["total"] == 3
    assert [h["id"] for h in found["shown"]] == ["EXR", "FXI", "SEE"]
    assert found["shown"][0]["name"] == "Exchange Rates"


def test_the_flow_list_is_requested_once_and_from_the_standard_path(spine):
    api.dataflows("ECB", "exchange")
    api.dataflows("ECB", "rates")
    assert spine.urls == [
        "https://data-api.ecb.europa.eu/service/dataflow/ECB/all/latest"]


def test_describe_flow_names_every_dimension_with_its_code_count(spine):
    got = api.describe_flow("ECB", "EXR")
    assert [(d["id"], d["codes"]) for d in got["dimensions"]] == [
        ("FREQ", 10), ("CURRENCY", 369), ("CURRENCY_DENOM", 369),
        ("EXR_TYPE", 36), ("EXR_SUFFIX", 6), ("TIME_PERIOD", 0)]
    assert got["dimensions"][0]["sample"][0] == {"id": "A", "name": "Annual"}
    assert "TIME_PERIOD is not part of the key" in got["note"]


def test_a_fully_english_codelist_is_not_flagged_as_needing_native_queries(spine):
    """The warning exists for ISTAT and INSEE. ECB labels everything in
    English, so raising it here would be noise on the busiest provider."""
    assert all("english_labels" not in d
               for d in api.describe_flow("ECB", "EXR")["dimensions"])


def test_search_codes_resolves_a_dimension_value_from_a_word(spine):
    """369 currencies is far past what a response should carry, which is why
    describe_flow samples and this exists."""
    got = api.search_codes("ECB", "EXR", "CURRENCY", "yen", 5)
    assert got == {"total": 1, "shown": [{"id": "JPY", "name": "Japanese yen"}]}


def test_search_codes_is_case_insensitive_about_the_dimension(spine):
    assert api.search_codes("ECB", "EXR", "currency", "yen")["total"] == 1


# --- fetching ----------------------------------------------------------------

def data_url(adapter) -> str:
    """The observation request. A fetch also asks for structure, before and
    after, so the last URL is not the interesting one."""
    return next(u for u in adapter.urls if "/data/" in u)


def test_a_dimension_key_becomes_a_positional_sdmx_key_in_the_url(spine):
    """SDMX keys are dot-separated in dimension order, not named. Getting the
    order wrong returns someone else's series with a 200 status."""
    api.fetch("ECB", "EXR", JPY, limit=3)
    assert data_url(spine) == ("https://data-api.ecb.europa.eu/service/data/EXR/"
                               "D.JPY.EUR.SP00.A?lastNObservations=4")


def test_the_period_bounds_reach_the_url_as_sdmx_spells_them(spine):
    api.fetch("ECB", "EXR", JPY, "2026-08-01", "2026-08-28", limit=3)
    assert "startPeriod=2026-08-01&endPeriod=2026-08-28" in data_url(spine)


def test_a_fetch_returns_the_packed_shape_with_units_resolved(spine):
    got = api.fetch("ECB", "EXR", JPY, limit=3)
    assert got["key"] == JPY  # invariant, so hoisted whole
    assert got["units"] == {"UNIT": "Japanese yen", "UNIT_MULT": "Units",
                            "UNIT_INDEX_BASE": "99Q1=100"}
    assert got["series"] == [{"key": {}, "observations": [
        ["2026-08-26", 185.62], ["2026-08-27", 185.61], ["2026-08-28", 185.92]]}]
    assert got["range"] == ["2026-08-26", "2026-08-28"]


def test_the_cap_is_sent_and_its_effect_is_reported(spine):
    """Four came back for a budget of three, so the fourth is the evidence that
    the series continues and `total` is a floor."""
    got = api.fetch("ECB", "EXR", JPY, limit=3)
    assert got["total"] == 4
    assert "most recent 3 of at least 4" in got["truncated"]


def test_a_cold_fetch_downloads_the_same_structure_twice(spine):
    """A recorded defect, not a specification. sdmx1 resolves a dict key by
    fetching the DSD itself, and `_unit_labels` then fetches it again through
    `_dsd`: the same 497KB URL twice, or 3.5MB twice on an IMF vintage. When
    this is fixed the test should fail and be rewritten, which is why it pins
    the count rather than asserting "at least one".
    """
    api.fetch("ECB", "EXR", JPY, limit=3)
    structures = [u for u in spine.urls if "references=all" in u]
    assert len(structures) == 2 and structures[0] == structures[1]


def test_describing_the_flow_first_saves_one_of_the_two(spine):
    """The prescribed discovery order goes through describe_flow, which warms
    `_dsd` — so `_unit_labels` costs nothing and only sdmx1's own key
    resolution still asks. One structure download instead of two."""
    api.describe_flow("ECB", "EXR")
    before = len(spine.urls)
    api.fetch("ECB", "EXR", JPY, limit=3)
    assert len([u for u in spine.urls[before:] if "references=all" in u]) == 1


def test_the_structure_is_paid_for_once_and_then_not_again(spine):
    """Both caches are warm after the first fetch, so a second is one request:
    the observations, which are never cached because a stale rate is a wrong
    answer."""
    api.fetch("ECB", "EXR", JPY, limit=3)
    before = len(spine.urls)
    api.fetch("ECB", "EXR", JPY, limit=3)
    assert spine.urls[before:] == [data_url(spine)]


# --- the structure-specific fallback -----------------------------------------

def test_the_two_bis_payloads_really_are_different_messages(load):
    """The premise of the fallback: one URL, two forms, chosen by Accept."""
    assert b"StructureSpecificData" in load("bis_data_structurespecific.xml")
    assert b"GenericData" in load("bis_data_generic.xml")


def test_the_generic_header_is_recorded_only_when_it_worked(monkeypatch):
    """A provider that fails both ways must not be remembered as one the
    generic header fixes; the next fetch would then send it and fail once
    rather than twice, which reads like a different bug."""
    always_ss = dict(BIS_ROUTES)
    always_ss["/data/WS_CBPOL/"] = ("bis_data_structurespecific.xml", BIS_XML)
    replay(monkeypatch, always_ss)

    with pytest.raises(sdmx.exceptions.XMLParseError):
        api.fetch("BIS", "WS_CBPOL", {"FREQ": "M", "REF_AREA": "JP"}, limit=3)
    assert api._NEEDS_GENERIC == set()


def test_bis_is_retried_with_the_generic_header_and_then_remembered(monkeypatch):
    bis = replay(monkeypatch, BIS_ROUTES)

    got = api.fetch("BIS", "WS_CBPOL", {"FREQ": "M", "REF_AREA": "JP"}, limit=3)
    assert got["units"] == {"UNIT_MEASURE": "Per cent per year",
                            "UNIT_MULT": "Units"}
    assert got["series"][0]["observations"][-1] == ["2026-07", 1.0]

    data = [(u, a) for u, a in zip(bis.urls, bis.accepts()) if "/data/" in u]
    assert len(data) == 3, "the failed default, the generic retry, the count check"
    assert "genericdata" not in data[0][1] and "genericdata" in data[1][1]
    assert data[0][0] == data[1][0], "same URL, different Accept"
    assert "detail=nodata" in data[2][0], "the series count, checked once"
    assert api._NEEDS_GENERIC == {"BIS"}

    # And having learned both, the second fetch is one request.
    before = len(bis.urls)
    api.fetch("BIS", "WS_CBPOL", {"FREQ": "M", "REF_AREA": "JP"}, limit=3)
    after = [(u, a) for u, a in zip(bis.urls[before:], bis.accepts()[before:])
             if "/data/" in u]
    assert len(after) == 1 and "genericdata" in after[0][1]


# --- what the evals found ----------------------------------------------------

def test_a_two_word_search_matches_words_rather_than_a_phrase(spine):
    """An eval asked IMF for 'national accounts' and got one hit, because the
    flow it wanted is named 'National Economic Accounts'. Matching the phrase
    as one substring reports a total that reads as authoritative."""
    assert api.dataflows("ECB", "exchange rates")["total"] == 1
    assert api.dataflows("ECB", "rates exchange")["total"] == 1
    assert api.dataflows("ECB", "exchange nonsense")["total"] == 0


def test_hits_come_back_closest_first(spine):
    """The other half of that eval: ILO answered "unemployment" with 108 flows
    in no order at all, and the agent read forty names and gave up. SESFOD
    carries "securities" 58 characters into a 119-character name; SEC is
    called it."""
    shown = [f["id"] for f in api.dataflows("ECB", "securities")["shown"]]
    assert shown[0] == "SEC"
    assert shown[-1] == "SESFOD"


def test_a_cut_list_says_it_was_cut(spine):
    """A total of 108 above 40 names reads as a catalogue to work through. It
    is a ranked list with a tail, and the next move is a word, not a guess."""
    cut = api.dataflows("ECB", "statistics", limit=3)
    assert cut["total"] > 3 and len(cut["shown"]) == 3
    assert "add a word" in cut["note"]
    assert "note" not in api.dataflows("ECB", "securities")

    # Without a search there is nothing to be close to, so it does not claim
    # an order it has not applied.
    assert "unordered" in api.dataflows("ECB", limit=3)["note"]


def test_a_fetch_names_the_codes_it_returns(spine):
    """JPY, EUR and SP00 are not an answer to what a series is. The labels come
    off the DSD this fetch has already downloaded to resolve units."""
    got = api.fetch("ECB", "EXR", JPY, limit=3)
    assert got["names"]["CURRENCY"] == {"JPY": "Japanese yen"}
    assert got["names"]["FREQ"] == {"D": "Daily"}
    assert got["names"]["CURRENCY_DENOM"] == {"EUR": "Euro"}


def test_naming_the_codes_costs_no_extra_request(spine):
    """It reads the structure the unit labels already needed. If it cost a
    request per fetch it would not be worth having."""
    api.describe_flow("ECB", "EXR")
    api.fetch("ECB", "EXR", JPY, limit=3)
    before = len(spine.urls)
    api.fetch("ECB", "EXR", JPY, limit=3)
    assert spine.urls[before:] == [data_url(spine)]

