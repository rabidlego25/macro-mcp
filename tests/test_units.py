"""What a number is measured in, which sdmx1 discards unless asked.

A bare 634751300000000.0 is not an answer to "what was Japan's GDP" — it is
634.75tn yen or 634.75bn depending on a multiplier the provider ships. These
assert on the label an agent ends up holding, not on the attribute surviving,
because a resolved code and an unresolved one look alike until you read them.
"""

import pandas as pd
import pytest

from conftest import parse, raw
from macro_mcp import bundesbank, singstat
from macro_mcp import sdmx_api as api


def message(name: str):
    return parse(bundesbank._repair(raw(name)))


def frame(rows, columns):
    return pd.DataFrame(rows, columns=columns)


# --- which attributes count as units -----------------------------------------

@pytest.mark.parametrize("name", [
    "UNIT",             # ECB
    "UNIT_MEASURE",     # BIS, ILO
    "UNIT_MULT",        # BIS, ECB, ILO
    "UNIT_INDEX_BASE",  # ECB
    "BBK_UNIT",         # Bundesbank prefixes its own
    "BBK_UNIT_MULT",
    "SCALE",            # IMF publishes no UNIT and populates this
])
def test_every_providers_spelling_of_a_unit_is_recognised(name):
    assert api._is_unit(name)


@pytest.mark.parametrize("name", [
    "COMPILATION", "TITLE", "SOURCE_REF", "DECIMALS", "OBS_STATUS",
    "SUPP_INFO_BREAKS", "TIME_FORMAT", "UNITED",  # not a unit, and must not match
])
def test_prose_and_process_attributes_are_not_units(name):
    """BIS ships 2.5KB of these per series, against a 6KB response."""
    assert not api._is_unit(name)


# --- where the unit lands in the response ------------------------------------

def test_an_invariant_unit_is_hoisted_out_of_every_observation():
    df = frame([("JP", "Per cent per year", "2024-01", 1.0),
                ("JP", "Per cent per year", "2024-02", 2.0)],
               ["REF_AREA", "UNIT_MEASURE", "TIME_PERIOD", "value"])
    out = api._pack(df, 500, ("UNIT_MEASURE",))
    assert out["units"] == {"UNIT_MEASURE": "Per cent per year"}
    assert out["key"] == {"REF_AREA": "JP"}
    assert out["series"][0]["observations"] == [["2024-01", 1.0], ["2024-02", 2.0]]


def test_a_unit_is_never_returned_inside_the_key():
    """An agent that echoed it back to fetch_data as a dimension would get an
    error from the provider, so key stays a key."""
    df = frame([("JP", "Units", "2024-01", 1.0)],
               ["REF_AREA", "UNIT_MULT", "TIME_PERIOD", "value"])
    out = api._pack(df, 500, ("UNIT_MULT",))
    assert "UNIT_MULT" not in out["key"]
    assert out["units"] == {"UNIT_MULT": "Units"}


def test_series_in_different_units_say_so_instead_of_interleaving():
    """The whole failure this exists to stop: percent and index in one response,
    distinguishable only by which country each row came from."""
    df = frame([("JP", "Per cent", "2024-01", 1.0),
                ("US", "Index", "2024-01", 100.0)],
               ["REF_AREA", "UNIT_MEASURE", "TIME_PERIOD", "value"])
    out = api._pack(df, 500, ("UNIT_MEASURE",))
    got = {s["key"]["REF_AREA"]: s["units"]["UNIT_MEASURE"] for s in out["series"]}
    assert got == {"JP": "Per cent", "US": "Index"}
    assert "UNIT_MEASURE" not in out["key"]


def test_a_response_with_no_unit_is_shaped_exactly_as_before():
    df = frame([("JP", "2024-01", 1.0)], ["REF_AREA", "TIME_PERIOD", "value"])
    out = api._pack(df, 500)
    assert "units" not in out
    assert out["series"][0] == {"key": {}, "observations": [["2024-01", 1.0]]}


def test_dropped_series_are_named_by_dimension_alone():
    """They carry no observations, so there is nothing to interpret."""
    df = frame([("A", "Index", "2024-01", 1.0), ("B", "Index", "2024-01", 2.0)],
               ["REF_AREA", "UNIT_MEASURE", "TIME_PERIOD", "value"])
    out = api._pack(df, 1, ("UNIT_MEASURE",))
    assert out["dropped_series"]["keys"] == [{"REF_AREA": "B"}]


# --- reading them off a real message -----------------------------------------

def test_bundesbank_yields_carry_their_own_spelling_of_a_unit():
    df, units = api._frame(message("bbk_data.xml"), "BBK", "BBSIS")
    assert "BBK_UNIT" in units
    assert set(df["BBK_UNIT"]) == {"PROZENT"}


def test_only_units_survive_out_of_everything_a_message_attaches():
    """The frame keeps dimensions, periods, values and units. Every other
    attribute is dropped at the frame, not at serialisation, so nothing
    downstream can hoist it into the response by accident."""
    msg = message("bbk_data.xml")
    attached = api._attribute_ids(msg)
    assert len(attached) > 1, attached  # the fixture does carry prose

    df, units = api._frame(msg, "BBK", "BBSIS")
    kept = [c for c in df.columns if c in attached]
    assert kept == list(units) == ["BBK_UNIT", "BBK_UNIT_MULT"]
    # What it threw away: a German title, an English one, decimals, a web
    # category, an internal id, the time format and the observation status.
    assert attached - set(units) and not (attached - set(units)) & set(df.columns)


def test_an_empty_attribute_value_reads_as_empty_whatever_shape_it_arrives_in():
    """IMF declares UNIT on its DSD and populates only SCALE, and pandas turns
    the gap into NaN. Left as the string "nan", it would hoist into the
    response as though the provider had stated something."""
    assert api._text(float("nan")) == ""
    assert api._text(None) == ""
    assert api._text("  Index  ") == "Index"


# --- Singapore ---------------------------------------------------------------

def test_singapore_stops_discarding_the_unit_it_already_fetched(monkeypatch):
    """uoM sat in the same rows frame() iterates, surfaced by search_codes and
    dropped on the way to the observations."""
    import json
    monkeypatch.setattr(singstat, "_table",
                        lambda flow, series="": json.loads(raw("singstat_annual.json"))["Data"])
    df = singstat.frame("M212881", {"SERIES": "1"}, None, None)
    assert set(df[singstat.UNIT]) == {"Index"}
    out = api._pack(df, 500, singstat.UNITS)
    assert out["units"] == {"UNIT": "Index"}
