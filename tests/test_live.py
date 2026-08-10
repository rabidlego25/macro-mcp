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
    rows = api.fetch("BBK", "BBSIS", key, "2024-01-02", "2024-01-03")["records"]
    assert [r["value"] for r in rows] == pytest.approx([2.13, 2.10])


def test_bis_japan_policy_rate_turns_positive_in_march_2024():
    rows = api.fetch("BIS", "WS_CBPOL", {"FREQ": "M", "REF_AREA": "JP"},
                     "2024-01", "2024-03")["records"]
    by_period = {r["TIME_PERIOD"]: r["value"] for r in rows}
    assert by_period["2024-01"] == pytest.approx(-0.1)
    assert by_period["2024-03"] == pytest.approx(0.05)


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


@pytest.mark.parametrize("provider,flow", [
    ("ABS", None),        # host moved; URL_FIXES
    ("LSD", None),        # path moved; URL_FIXES
    ("INEGI", None),      # agency id differs; AGENCY
    ("BBK", None),        # bespoke adapter
])
def test_repaired_providers_still_list_dataflows(provider, flow):
    out = api.dataflows(provider, "", 1)
    assert out.get("total", 0) > 0, out
