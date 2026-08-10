"""Singapore Table Builder adapter.

The risk here is not parse failure but quiet mistranslation: SingStat's periods
are neither ISO nor sortable, and a table that came back looking fine while
sitting in its own notation would silently refuse to join against every other
provider.
"""

import json

import pytest

from conftest import raw
from macro_mcp import singstat
from macro_mcp import sdmx_api as api


@pytest.fixture
def offline(monkeypatch):
    """Serve the saved responses in place of the network."""
    def fake(path, params=None):
        if path == "resourceid":
            return json.loads(raw("singstat_search.json"))["Data"]
        name = "monthly" if "M213751" in path else "annual"
        return json.loads(raw(f"singstat_{name}.json"))["Data"]

    monkeypatch.setattr(singstat, "_get", fake)
    singstat._search.cache_clear()
    singstat._table.cache_clear()
    yield
    singstat._search.cache_clear()
    singstat._table.cache_clear()


@pytest.mark.parametrize("given,want", [
    ("1961", "1961"),
    ("1961 Jan", "1961-01"),
    ("1961 Dec", "1961-12"),
    ("1961 1Q", "1961-Q1"),
    ("1961 4Q", "1961-Q4"),
    ("1961 1H", "1961-S1"),
    ("1961 2H", "1961-S2"),
])
def test_periods_are_rewritten_to_sdmx_form(given, want):
    assert singstat.period(given) == want


def test_unrecognised_periods_pass_through_untouched():
    """Better an obviously foreign period than a confidently wrong one."""
    assert singstat.period("sometime in 1961") == "sometime in 1961"


def test_month_names_do_not_sort_before_normalisation():
    """The reason normalising is not cosmetic: alphabetically April leads."""
    raw_keys = sorted(["1961 Jan", "1961 Apr", "1961 Feb"])
    assert raw_keys[0] == "1961 Apr"
    assert sorted(singstat.period(k) for k in raw_keys)[0] == "1961-01"


@pytest.mark.parametrize("start,end,want", [
    (None, None, True),
    ("2024", "2024", True),      # bare year against a month
    ("2024-02", None, False),
    (None, "2023", False),
    ("2020", "2024", True),
])
def test_range_is_compared_on_a_prefix(start, end, want):
    """end="2024" has to keep 2024-01, which sorts after the bare year."""
    assert singstat._within("2024-01", start, end) is want


def test_catalogue_search_returns_ids_and_titles(offline):
    out = api.dataflows("SINGSTAT", "consumer price index", 3)
    assert out["total"] == 27
    assert len(out["shown"]) == 3
    assert out["shown"][0]["id"] == "M213801"
    assert "Consumer Price Index" in out["shown"][0]["name"]


def test_search_is_required_because_there_is_no_catalogue_listing(offline):
    assert "error" in api.dataflows("SINGSTAT", None, 10)


def test_describe_exposes_rows_as_one_dimension(offline):
    out = api.describe_flow("SINGSTAT", "M213801")
    assert out["frequency"] == "Annual"
    assert out["dimensions"][0]["id"] == "SERIES"
    assert out["dimensions"][0]["sample"][0] == {"id": "1", "name": "All Items"}


def test_codes_reject_a_dimension_the_table_does_not_have(offline):
    assert "error" in api.search_codes("SINGSTAT", "M213801", "REF_AREA", "", 5)


def test_fetch_returns_sdmx_periods_and_numeric_values(offline):
    out = api.fetch("SINGSTAT", "M213801", {"SERIES": "1"}, "2020", "2024")
    assert out["key"] == {"SERIES": "1"}
    assert out["series"][0]["observations"] == [
        ["2020", 85.794], ["2021", 87.781], ["2022", 93.163],
        ["2023", 97.666], ["2024", 100.0]]


def test_fetch_on_a_monthly_table_keeps_a_whole_year_for_a_bare_end(offline):
    out = api.fetch("SINGSTAT", "M213751", {"SERIES": "1"}, "2024", "2024")
    assert out["total"] == 12
    assert out["range"] == ["2024-01", "2024-12"]
    assert out["series"][0]["observations"][0] == ["2024-01", 98.752]


def test_values_arrive_as_strings_and_must_end_up_numeric(offline):
    """The API quotes its numbers; leaving them as text would make every
    downstream comparison a string comparison."""
    assert '"value":"85.794"' in raw("singstat_annual.json").decode()
    out = api.fetch("SINGSTAT", "M213801", {"SERIES": "1"}, "2020", "2020")
    assert isinstance(out["series"][0]["observations"][0][1], float)
