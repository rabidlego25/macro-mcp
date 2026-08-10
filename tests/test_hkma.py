"""Hong Kong Monetary Authority adapter.

The dangerous call here is the date range. HKMA accepts `from` and `to` and
ignores them unless `choose` names the period column, so a narrow request comes
back as the whole history with a 200 — and once `choose` is supplied the
comparison is literal, so a bound coarser than the period selects nothing at
all. Both mistakes return a well-formed answer, which is why these assert on
the query that was sent and the rows that survived rather than on success.
"""

import json

import pytest

from conftest import raw
from macro_mcp import cache, hkma
from macro_mcp import sdmx_api as api


@pytest.fixture
def offline(monkeypatch):
    """Replay saved responses and record what was asked for."""
    sent = []

    def fake(flow, params):
        sent.append(params)
        name = "daily" if "interbank-ir" in flow else "quarterly"
        return json.loads(raw(f"hkma_{name}.json"))["result"]["records"]

    monkeypatch.setattr(hkma, "_get", fake)
    hkma._columns.cache_clear()
    yield sent
    hkma._columns.cache_clear()


def test_every_dataset_belongs_to_a_section():
    """The path is built from the section, so a slug missing one 404s."""
    assert len(hkma.FLOWS) == 125
    assert all(hkma.FLOWS[f] for f in hkma.FLOWS)
    assert hkma.FLOWS["capital-adequacy"] == "monthly-statistical-bulletin/banking"


def test_catalogue_is_searchable_without_a_catalogue_endpoint(offline):
    out = api.dataflows("HKMA", "interbank", 10)
    assert out["total"] >= 4
    assert "hk-interbank-ir-daily" in [s["id"] for s in out["shown"]]


def test_search_matches_words_as_well_as_slugs(offline):
    """A slug is hyphenated; an agent will type spaces."""
    assert api.dataflows("HKMA", "capital adequacy", 5)["shown"][0]["id"] == "capital-adequacy"


def test_describe_reads_the_period_column_rather_than_assuming_one(offline):
    """HKMA names it end_of_date, end_of_day, end_of_month or end_of_quarter
    depending on the dataset. Guessing wrong makes the period a data column."""
    assert api.describe_flow("HKMA", "capital-adequacy")["frequency"] == "Quarterly"
    assert api.describe_flow("HKMA", "hk-interbank-ir-daily")["frequency"] == "Daily"


def test_describe_exposes_columns_as_one_dimension(offline):
    dim = api.describe_flow("HKMA", "capital-adequacy")["dimensions"][0]
    assert dim["id"] == "SERIES"
    assert dim["codes"] == 4  # the period column is not one of them
    assert "end_of_quarter" not in [c["id"] for c in dim["sample"]]


def test_an_unknown_dataset_is_named_rather_than_requested(offline):
    assert "error" in api.describe_flow("HKMA", "no-such-table")


def test_codes_reject_a_dimension_the_dataset_does_not_have(offline):
    assert "error" in api.search_codes("HKMA", "capital-adequacy", "REF_AREA", "", 5)


def test_an_unknown_series_fails_loudly(offline):
    with pytest.raises(ValueError, match="no series"):
        hkma.frame("capital-adequacy", {"SERIES": "not_a_column"})


def test_a_bound_matching_the_period_width_is_sent_to_the_service(offline):
    """With `choose`, the service filters and the download stays small."""
    hkma.frame("hk-interbank-ir-daily", {"SERIES": "ir_overnight"},
               "2024-01-02", "2024-01-10")
    assert offline[-1]["from"] == "2024-01-02"
    assert offline[-1]["choose"] == "end_of_day"


def test_a_coarser_bound_is_never_sent_because_the_match_is_literal(offline):
    """from=2024 against 2024-03 selects nothing and returns an empty result
    with a 200, so the range is applied here instead."""
    out = hkma.frame("capital-adequacy", {"SERIES": "total_cap_ratio"}, "2024", "2024")
    assert "from" not in offline[-1] and "choose" not in offline[-1]
    assert sorted(out["TIME_PERIOD"]) == ["2024-03", "2024-06", "2024-09", "2024-12"]


def test_choose_never_travels_without_a_bound(offline):
    """It is a 400 on its own."""
    hkma.frame("capital-adequacy", {"SERIES": "total_cap_ratio"})
    assert "choose" not in offline[-1]


def test_the_range_is_enforced_here_even_when_the_service_was_asked(offline):
    """The saved response is the full history; a request for one quarter must
    not return thirteen years of it just because the query looked right."""
    out = hkma.frame("capital-adequacy", {"SERIES": "total_cap_ratio"},
                     "2024-03", "2024-03")
    assert list(out["TIME_PERIOD"]) == ["2024-03"]


def test_several_series_come_back_as_separate_series(offline):
    out = api.fetch("HKMA", "hk-interbank-ir-daily", {"SERIES": "ir_overnight+ir_3m"},
                    "2024-01-02", "2024-01-10")
    assert {s["key"]["SERIES"] for s in out["series"]} == {"ir_overnight", "ir_3m"}


def test_values_end_up_numeric(offline):
    out = api.fetch("HKMA", "capital-adequacy", {"SERIES": "total_cap_ratio"},
                    "2024-03", "2024-03")
    assert out["series"][0]["observations"] == [["2024-03", pytest.approx(21.1223, abs=1e-3)]]


def test_a_retired_dataset_says_how_to_refresh_the_table(monkeypatch):
    """The table is a snapshot of a catalogue HKMA does not publish, so it goes
    stale. A 404 from a URL the agent never composed is not a useful answer."""
    class Gone:
        status_code = 404

    monkeypatch.setattr(cache, "session", lambda: type("S", (), {"get": lambda *a, **k: Gone()})())
    with pytest.raises(RuntimeError, match="hkma_catalogue"):
        hkma._get("capital-adequacy", {})


def test_a_dataset_outside_the_table_is_refused_before_a_request_is_made():
    with pytest.raises(ValueError, match="no HKMA dataset"):
        hkma._get("invented-slug", {})
