"""Network tests against the real services. Opt in with MACRO_MCP_LIVE=1.

Two kinds of assertion live here and they mean opposite things, so they are
separated by the `revisable` marker rather than run together.

Unmarked, the default: structure. A flow exists, a key resolves, a period
joins, a date range binds. These are stable, and a failure means the provider
moved or renamed something, or this server broke. Fail loudly.

Marked `revisable`: a number is still the number it was. A CPI is rebased, a
national account is revised, a vintage lands — and the assertion goes red
because the provider did its job. Running these on a schedule and treating red
as breakage teaches you to ignore the suite, in a project whose whole subject
is that revisions happen quietly. Run them apart, and read a failure as news
about the data rather than about the code:

    uv run pytest -m "not revisable"   # must pass
    uv run pytest -m revisable         # reports what moved
"""

import os

import pytest

from macro_mcp import cache, entities, fx, hkma, sdmx_api as api, vintages

pytestmark = pytest.mark.skipif(
    os.environ.get("MACRO_MCP_LIVE") != "1",
    reason="set MACRO_MCP_LIVE=1 to run tests that hit the network")


def test_units_arrive_resolved_rather_than_as_provider_codes():
    """BIS sends UNIT_MEASURE="368", which is no more use than the bare number
    was. The label is the product; the code is not."""
    out = api.fetch("BIS", "WS_CBPOL", {"FREQ": "M", "REF_AREA": "JP"},
                    "2024-01", "2024-02")
    assert out["units"]["UNIT_MEASURE"] == "Per cent per year"
    assert out["units"]["UNIT_MULT"] == "Units"
    assert "UNIT_MEASURE" not in out["key"]  # a unit is not a dimension


def test_imf_publishes_no_unit_but_does_publish_a_scale():
    """Its DSD declares UNIT and never populates it. An empty attribute must
    not reach the response as though the provider had stated something."""
    out = api.fetch("IMF_DATA", "CPI",
                    {"COUNTRY": "JPN", "INDEX_TYPE": "CPI", "FREQUENCY": "M"},
                    "2024-01", "2024-02")
    assert out["units"] == {"SCALE": "Units"}


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


def test_limit_bounds_the_download_and_not_only_the_response():
    """ECB's daily EXR is 7,143 observations and 4.9MB. Answering a three-day
    question used to cost all of it; lastNObservations makes it 6KB.

    `total` is what arrives, so it is the measurement: if a provider stops
    honouring the parameter this reads in the thousands rather than failing to
    parse, and nothing else would notice.
    """
    key = {"FREQ": "D", "CURRENCY": "JPY", "CURRENCY_DENOM": "EUR",
           "EXR_TYPE": "SP00", "EXR_SUFFIX": "A"}
    out = api.fetch("ECB", "EXR", key, limit=3)
    assert len(out["series"][0]["observations"]) == 3
    assert out["total"] <= 4, "the whole history was downloaded to return three"
    assert "of at least" in out["truncated"]


def test_a_series_shorter_than_the_budget_is_still_counted_exactly():
    """The cap is limit + 1, so a complete series arrives short of it and says
    how long it is rather than reporting a floor."""
    out = api.fetch("BIS", "WS_CBPOL", {"FREQ": "M", "REF_AREA": "JP"},
                    "2024-01", "2024-03")
    assert out["total"] == 3
    assert "truncated" not in out


def test_multi_country_query_groups_into_one_series_per_country():
    out = api.fetch("BIS", "WS_CBPOL", {"FREQ": "M", "REF_AREA": "JP+US"},
                    "2024-01", "2024-03")
    assert out["key"] == {"FREQ": "M"}
    assert {s["key"]["REF_AREA"] for s in out["series"]} == {"JP", "US"}


def _one(out):
    return dict(out["series"][0]["observations"])


def test_fx_conventions_differ():
    """The reason convention is a required argument rather than a default."""
    avg = _one(fx.period_rate("JPY", "2024-01", "2024-01", "average"))["2024-01"]
    eop = _one(fx.period_rate("JPY", "2024-01", "2024-01", "end_of_period"))["2024-01"]
    assert abs(eop - avg) > 0.5
    assert avg == pytest.approx(159.458, abs=0.01)
    assert eop == pytest.approx(160.19, abs=0.01)


def test_a_cross_rate_is_derived_and_says_so():
    """The ECB publishes no USD/JPY rate. This one is JPY/EUR over USD/EUR, and
    the response has to say that rather than pass it off as a published rate."""
    got = fx.spot("USD", "JPY", "2024-01-05")
    assert got["derived"] is True and "publishes no USD/JPY" in got["note"]
    usd = _one(fx.period_rate("USD", "2024-01-05", "2024-01-05", "average", "D"))
    jpy = _one(fx.period_rate("JPY", "2024-01-05", "2024-01-05", "average", "D"))
    assert got["rate"] == pytest.approx(jpy["2024-01-05"] / usd["2024-01-05"])


def test_a_weekend_returns_the_last_publication_day():
    """2024-01-06 was a Saturday; reference rates are TARGET business days."""
    got = fx.spot("EUR", "USD", "2024-01-06")
    assert got["date"] == "2024-01-05"
    assert "not a publication day" in got["note_date"]


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
    assert [p for p in obs] == ["2020", "2021", "2022", "2023", "2024"]
    assert out["units"] == {"UNIT": "Index"}


@pytest.mark.revisable
def test_singapore_cpi_still_reads_as_it_did():
    """Rebasing moves every number in the series at once."""
    hits = api.dataflows("SINGSTAT", "consumer price index", 40)["shown"]
    annual = next(h for h in hits if h["name"].endswith("Annual"))
    obs = dict(api.fetch("SINGSTAT", annual["id"], {"SERIES": "1"}, "2020", "2024")
               ["series"][0]["observations"])
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


@pytest.mark.parametrize("provider", ["ILO", "IMF_DATA", "ECB", "BIS"])
def test_the_shipped_index_still_describes_the_live_catalogue(provider, uncached):
    """The index is a snapshot and snapshots rot, which the README lists as this
    project's standing maintenance debt. This turns that into a notification:
    it samples what the index claims against what the provider serves now.

    Ten flows rather than all of them, because the point is to catch a
    catalogue that moved, and a provider that renamed every flow will fail on
    the first ten. Rebuild with `uv run python -m scripts.catalogue`."""
    claimed = api._catalogue()["providers"][provider]
    live = api._flows(provider)
    sample = claimed[:: max(1, len(claimed) // 10)][:10]
    missing = [ident for ident, *_ in sample if ident not in live]
    assert not missing, f"{provider} no longer serves {missing}; rebuild the index"


def test_the_index_routes_to_a_provider_that_really_has_it(uncached):
    """The whole contract of the index in one assertion: what it says is a
    hint, and the live call it points at has to agree. It reported ILO for
    unemployment where IMF returns nothing, which is the eval it was built
    for."""
    routed = api.dataflows("*", "unemployment")
    best = routed["providers"][0]
    assert api.dataflows(best["provider"], "unemployment")["total"] > 0
    assert "ILO" in [p["provider"] for p in routed["providers"]]


def test_imf_codes_resolve_through_the_concept_not_the_dimension():
    """IMF's dimensions declare no local representation, so a codelist is only
    reachable via the concept each one identifies. Without that, every dimension
    reported zero codes and search_codes could match nothing."""
    dims = {d["id"]: d["codes"] for d in api.describe_flow("IMF_DATA", "CPI")["dimensions"]}
    assert dims["COUNTRY"] > 200 and dims["INDEX_TYPE"] > 10
    assert api.search_codes("IMF_DATA", "CPI", "COUNTRY", "japan", 3)["shown"][0]["id"] == "JPN"


_JP_CPI = {"COUNTRY": "JPN", "INDEX_TYPE": "CPI", "COICOP_1999": "_T",
           "TYPE_OF_TRANSFORMATION": "IX", "FREQUENCY": "M"}


def test_imf_japan_cpi_arrives_with_joinable_periods():
    """IMF writes months as 2024-M01, which joins against nothing."""
    out = api.fetch("IMF_DATA", "CPI", _JP_CPI, "2024-01", "2024-03")
    assert [p for p, _ in out["series"][0]["observations"]] == [
        "2024-01", "2024-02", "2024-03"]


@pytest.mark.revisable
def test_imf_japan_cpi_still_reads_as_it_did():
    out = api.fetch("IMF_DATA", "CPI", _JP_CPI, "2024-01", "2024-03")
    assert [v for _, v in out["series"][0]["observations"]] == [
        pytest.approx(106.9), pytest.approx(106.9), pytest.approx(107.2)]


def test_hkma_hibor_overnight_spiked_at_the_2024_year_end():
    """Hong Kong interbank rates, which the international providers do not
    carry at this granularity."""
    out = api.fetch("HKMA", "hk-interbank-ir-daily", {"SERIES": "ir_overnight"},
                    "2024-01-02", "2024-01-05")
    assert out["series"][0]["observations"][0] == ["2024-01-02", pytest.approx(4.40452)]
    assert out["range"] == ["2024-01-02", "2024-01-05"]


def test_hkma_ignores_a_date_range_unless_the_period_column_is_named():
    """The reason the adapter filters what arrives. Asked without `choose`,
    HKMA answers a four-day request with its entire history and a 200."""
    flow = "monthly-statistical-bulletin/er-ir/hk-interbank-ir-daily"
    url = f"{hkma.BASE}/{flow}"
    window = {"from": "2024-01-02", "to": "2024-01-05", "pagesize": 20000}
    loose = cache.session().get(url, params=window, timeout=cache.TIMEOUT).json()
    tight = cache.session().get(url, params={**window, "choose": "end_of_day"},
                                timeout=cache.TIMEOUT).json()
    assert loose["header"]["success"] and tight["header"]["success"]
    assert loose["result"]["datasize"] > 1000   # the whole series, silently
    assert tight["result"]["datasize"] == 4


def test_hkma_a_coarse_bound_would_silently_return_nothing():
    """The other half of the trap: with `choose` the comparison is literal, so
    a year against a quarter matches no rows at all."""
    url = f"{hkma.BASE}/monthly-statistical-bulletin/banking/capital-adequacy"
    body = cache.session().get(url, params={"choose": "end_of_quarter", "from": "2024",
                                            "to": "2024", "pagesize": 20000},
                               timeout=cache.TIMEOUT).json()
    assert body["header"]["success"]
    assert body["result"]["datasize"] == 0
    # The adapter is asked the same thing and gets it right.
    out = api.fetch("HKMA", "capital-adequacy", {"SERIES": "total_cap_ratio"}, "2024", "2024")
    assert out["total"] == 4


def test_imf_vintages_show_a_revision_the_current_flow_hides():
    """Japan's 2024 nominal GDP was revised up by 525.3bn yen between the April
    2026 vintage and the current release. Reading only the current flow gives
    the revised figure with no sign it ever said anything else."""
    key = {"COUNTRY": "JPN", "INDICATOR": "B1GQ", "PRICE_TYPE": "V",
           "TYPE_OF_TRANSFORMATION": "XDC", "FREQUENCY": "A"}
    out = vintages.compare("IMF_DATA", "ANEA", key, "2024", "2024")
    assert out["vintages"][-1] == "ANEA"
    revision = next(r for r in out["revisions"] if r["period"] == "2024")
    assert revision["between"][1] == "ANEA"
    assert revision["was"] != revision["now"]


@pytest.mark.revisable
def test_the_size_of_japans_gdp_revision_is_still_what_it_was():
    """`now` is read from the current flow, so this goes red the next time the
    IMF revises — which is the event the tool exists to surface, not a bug."""
    key = {"COUNTRY": "JPN", "INDICATOR": "B1GQ", "PRICE_TYPE": "V",
           "TYPE_OF_TRANSFORMATION": "XDC", "FREQUENCY": "A"}
    out = vintages.compare("IMF_DATA", "ANEA", key, "2024", "2024")
    revision = next(r for r in out["revisions"] if r["period"] == "2024")
    assert revision["was"] == pytest.approx(634226000000000.0)
    assert revision["now"] == pytest.approx(634751300000000.0)


def test_a_flow_without_vintages_is_not_silently_treated_as_having_none():
    """CO2 emissions is published once, not as monthly vintages. Saying so is
    the point: an empty list alone reads like a lookup that failed."""
    out = vintages.available("IMF_DATA", "CO2E")
    assert out["vintages"] == [] and "as-revised" in out["note"]


def test_the_vintages_of_a_flow_are_not_confused_with_a_longer_named_one():
    """CPI and CPI_WCA both have vintages, and the catalogue is searched by
    substring, so CPI must not collect CPI_WCA's."""
    got = vintages.available("IMF_DATA", "CPI")["vintages"]
    assert got and all(vintages.family(v) == "CPI" for v in got)
