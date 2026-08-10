"""Network tests against the real services. Opt in with MACRO_MCP_LIVE=1.

Values are historical and therefore stable; a change here means the provider
moved, renamed something, or revised the series.
"""

import os

import pytest

from macro_mcp import entities, fx, sdmx_api as api

pytestmark = pytest.mark.skipif(
    os.environ.get("MACRO_MCP_LIVE") != "1",
    reason="set MACRO_MCP_LIVE=1 to run tests that hit the network")


def test_bundesbank_ten_year_bund_yield():
    key = {"BBK_STD_FREQ": "D", "BBK_SEIS_BEARER_REG": "I", "BBK_SEIS_ITEM": "ZAR",
           "BBK_SEIS_VALUATION": "ZI", "BBK_STD_CURRENCY": "EUR",
           "BBK_SEIS_ISSUER_CLASS": "S1311", "BBK_SEIS_LISTED_SUB": "B",
           "BBK_SEIS_SECURITY_CLASS": "A604", "BBK_SEIS_MATURITY": "R10XX",
           "BBK_SEIS_INTEREST_TYPE": "R", "BBK_SEIS_INTEREST_RATE": "A",
           "BBK_SEIS_REDEMPTION": "A", "BBK_SEIS_CERTIFICATE": "_Z",
           "BBK_SEIS_COVERAGE": "_Z", "BBK_SEIS_RATING": "A"}
    out = api.fetch("BBK", "BBSIS", key, "2024-01-01", "2024-01-03")
    assert out["series"][0]["observations"] == [["2024-01-02", pytest.approx(2.13)],
                                                ["2024-01-03", pytest.approx(2.10)]]
    assert out["empty"] == 1  # New Year's Day carries OBS_STATUS=K and no value
    assert out["key"]["BBK_SEIS_MATURITY"] == "R10XX"  # key hoisted, not per-row


def test_bis_japan_policy_rate_turns_positive_in_march_2024():
    out = api.fetch("BIS", "WS_CBPOL", {"FREQ": "M", "REF_AREA": "JP"},
                    "2024-01", "2024-03")
    by_period = dict(out["series"][0]["observations"])
    assert by_period["2024-01"] == pytest.approx(-0.1)
    assert by_period["2024-03"] == pytest.approx(0.05)


def test_multi_country_query_groups_into_one_series_per_country():
    out = api.fetch("BIS", "WS_CBPOL", {"FREQ": "M", "REF_AREA": "JP+US"},
                    "2024-01", "2024-03")
    assert out["key"] == {"FREQ": "M"}
    assert {s["key"]["REF_AREA"] for s in out["series"]} == {"JP", "US"}


def test_fx_conventions_differ():
    """The reason convention is a required argument rather than a default."""
    avg = fx.period_rate("JPY", "2024-01", "2024-01", "average")["rates"]["2024-01"]
    eop = fx.period_rate("JPY", "2024-01", "2024-01", "end_of_period")["rates"]["2024-01"]
    assert avg == pytest.approx(159.458, abs=0.01)
    assert eop == pytest.approx(160.19, abs=0.01)
    assert abs(eop - avg) > 0.5


def test_entity_search_finds_native_script_names():
    """A legal-name filter returns nothing here; fulltext is why this works."""
    hits = entities.search("Toyota Motor", "JP", 5)["hits"]
    toyota = next(h for h in hits if h["lei"] == "5493006W3QUS5LMH6R84")
    assert toyota["name"] == "トヨタ自動車株式会社"
    assert "Toyota Motor Corporation" in toyota["other_names"]


def test_english_query_finds_a_french_dataflow():
    shown = api.dataflows("INSEE", "unemployment", 10)["shown"]
    assert any(s["id"] == "CHOMAGE-TRIM-NATIONAL" for s in shown)


def test_singstat_serves_singapore_cpi_on_the_shared_grammar():
    """Not SDMX, but reached through the same tools and returning the same
    shape, with periods rewritten so they join against the other providers."""
    hits = api.dataflows("SINGSTAT", "consumer price index", 40)["shown"]
    annual = next(h for h in hits if h["name"].endswith("Annual"))

    codes = api.search_codes("SINGSTAT", annual["id"], "SERIES", "all items", 5)
    assert codes["shown"][0]["name"] == "All Items"

    out = api.fetch("SINGSTAT", annual["id"], {"SERIES": "1"}, "2020", "2024")
    obs = dict(out["series"][0]["observations"])
    assert obs["2024"] == pytest.approx(100.0)      # 2024 is the base year
    assert obs["2020"] == pytest.approx(85.794, abs=0.01)


def test_singstat_monthly_periods_come_back_in_sdmx_form():
    """The API says "2024 Jan"; anything but 2024-01 fails to join."""
    out = api.fetch("SINGSTAT", "M213751", {"SERIES": "1"}, "2024", "2024")
    assert [p for p, _ in out["series"][0]["observations"]][:3] == [
        "2024-01", "2024-02", "2024-03"]


def test_oecd_flow_ids_carry_an_agency_prefix_and_still_describe():
    """sdmx1 puts the whole AGENCY:ID(VERSION) key in the id slot and builds a
    URL OECD rejects with a 400, which made all 1500-odd flows list-only."""
    flow = api.dataflows("OECD", "air emission", 5)["shown"][0]["id"]
    assert ":" in flow and "(" in flow
    dims = api.describe_flow("OECD", flow)["dimensions"]
    assert [d["id"] for d in dims], dims


@pytest.mark.parametrize("provider", [
    "ABS",        # host moved; URL_FIXES
    "LSD",        # path moved; URL_FIXES
    "INEGI",      # agency id differs; AGENCY
    "BBK",        # bespoke adapter
])
def test_repaired_providers_still_list_dataflows(provider, uncached):
    """The point is to catch endpoint drift, so this must reach the network.
    A cached dataflow list would pass long after the provider had moved."""
    out = api.dataflows(provider, "", 1)
    assert out.get("total", 0) > 0, out


def test_imf_codes_resolve_through_the_concept_not_the_dimension():
    """IMF's dimensions declare no local representation, so a codelist is only
    reachable via the concept each one identifies. Without that, every dimension
    reported zero codes and search_codes could match nothing."""
    dims = {d["id"]: d["codes"] for d in api.describe_flow("IMF_DATA", "CPI")["dimensions"]}
    assert dims["COUNTRY"] > 200 and dims["INDEX_TYPE"] > 10
    assert api.search_codes("IMF_DATA", "CPI", "COUNTRY", "japan", 3)["shown"][0]["id"] == "JPN"


def test_imf_japan_cpi_arrives_with_joinable_periods():
    key = {"COUNTRY": "JPN", "INDEX_TYPE": "CPI", "COICOP_1999": "_T",
           "TYPE_OF_TRANSFORMATION": "IX", "FREQUENCY": "M"}
    out = api.fetch("IMF_DATA", "CPI", key, "2024-01", "2024-03")
    assert out["series"][0]["observations"] == [["2024-01", pytest.approx(106.9)],
                                                ["2024-02", pytest.approx(106.9)],
                                                ["2024-03", pytest.approx(107.2)]]
