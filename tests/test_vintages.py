"""Point-in-time reads.

The failure this guards against is not an exception but a false negative: a
comparison that reports no revision because the vintages were fetched in the
wrong order, or because a vintage that simply lacks the key was read as one
that agrees.
"""

import pytest

from macro_mcp import vintages
from macro_mcp import sdmx_api as api

CATALOGUE = ["ANEA", "ANEA_2026_JAN_VINTAGE", "ANEA_2026_FEB_VINTAGE",
             "ANEA_2026_APR_VINTAGE", "ANEA_2026_MAY_VINTAGE",
             "QANEA", "CPI"]


@pytest.fixture
def offline(monkeypatch):
    """A fixed catalogue, and observations chosen per vintage."""
    monkeypatch.setattr(api, "dataflows", lambda p, q, n: {
        "total": len(CATALOGUE),
        "shown": [{"id": i, "name": i} for i in CATALOGUE if q in i]})

    def fetch(provider, flow, key, start=None, end=None, limit=500):
        by_flow = {
            "ANEA_2026_JAN_VINTAGE": [["2023", 100.0], ["2024", 200.0]],
            "ANEA_2026_FEB_VINTAGE": [["2023", 100.0], ["2024", 200.0]],
            "ANEA_2026_APR_VINTAGE": [["2023", 101.0], ["2024", 200.0]],
            "ANEA_2026_MAY_VINTAGE": [],
            "ANEA": [["2023", 101.0], ["2024", 250.0]],
        }
        obs = by_flow.get(flow, [])
        return {"series": [{"key": {}, "observations": obs}] if obs else []}

    monkeypatch.setattr(api, "fetch", fetch)


def test_a_vintage_id_resolves_to_its_family():
    assert vintages.family("ANEA_2026_JAN_VINTAGE") == "ANEA"
    assert vintages.family("ANEA") == "ANEA"
    assert vintages.family("CPI_WCA_2026_MAY_VINTAGE") == "CPI_WCA"


def test_vintages_order_by_publication_not_alphabetically():
    """APR sorts before FEB as a string, which would invert every revision."""
    got = sorted(["ANEA_2026_MAY_VINTAGE", "ANEA_2026_FEB_VINTAGE",
                  "ANEA_2026_APR_VINTAGE", "ANEA_2026_JAN_VINTAGE"],
                 key=vintages.released)
    assert [v.split("_")[2] for v in got] == ["JAN", "FEB", "APR", "MAY"]


def test_the_current_flow_sorts_after_every_vintage():
    assert vintages.released("ANEA") > vintages.released("ANEA_2026_MAY_VINTAGE")


def test_available_lists_the_family_in_publication_order(offline):
    out = vintages.available("IMF_DATA", "ANEA")
    assert out["vintages"] == ["ANEA_2026_JAN_VINTAGE", "ANEA_2026_FEB_VINTAGE",
                               "ANEA_2026_APR_VINTAGE", "ANEA_2026_MAY_VINTAGE", "ANEA"]
    assert out["current"] == "ANEA"


def test_a_neighbouring_family_is_not_swept_in(offline):
    """The catalogue is searched by substring, so QANEA matches "ANEA"."""
    assert "QANEA" not in vintages.available("IMF_DATA", "ANEA")["vintages"]


def test_a_flow_without_vintages_says_so_rather_than_returning_nothing(offline):
    out = vintages.available("IMF_DATA", "CPI")
    assert out["vintages"] == []
    assert "as-revised" in out["note"]


def test_revisions_are_reported_between_the_vintages_that_differ(offline):
    out = vintages.compare("IMF_DATA", "ANEA", {"COUNTRY": "JPN"})
    assert [(r["period"], r["was"], r["now"]) for r in out["revisions"]] == [
        ("2023", 100.0, 101.0), ("2024", 200.0, 250.0)]
    assert out["revisions"][0]["between"] == ["ANEA_2026_FEB_VINTAGE",
                                              "ANEA_2026_APR_VINTAGE"]


def test_a_vintage_missing_the_key_is_reported_not_read_as_agreement(offline):
    """Coverage varies between vintages. Treating an absent key as unchanged
    would hide the revision that follows it."""
    out = vintages.compare("IMF_DATA", "ANEA", {"COUNTRY": "JPN"})
    assert out["no_data"] == ["ANEA_2026_MAY_VINTAGE"]
    assert "ANEA_2026_MAY_VINTAGE" not in out["vintages"]
    # The revision either side of the empty vintage still shows up.
    assert any(r["between"] == ["ANEA_2026_APR_VINTAGE", "ANEA"] for r in out["revisions"])


def test_the_percentage_is_signed_and_relative(offline):
    out = vintages.compare("IMF_DATA", "ANEA", {"COUNTRY": "JPN"})
    by_period = {r["period"]: r["change_pct"] for r in out["revisions"]}
    assert by_period["2024"] == pytest.approx(25.0)


def test_limit_drops_the_oldest_vintages(offline):
    """Each vintage is a separate request against a slow service, so the limit
    bounds requests. The recent ones are what a revision question is about."""
    out = vintages.compare("IMF_DATA", "ANEA", {"COUNTRY": "JPN"}, limit=4)
    assert "ANEA_2026_JAN_VINTAGE" not in out["vintages"]
    assert out["vintages"][-1] == "ANEA"


def test_a_vintage_without_the_key_still_costs_a_request(offline):
    """The budget is spent before coverage is known, so asking for two can
    leave one readable. That is reported rather than quietly topped up: the
    alternative is an unbounded number of requests to a slow service."""
    out = vintages.compare("IMF_DATA", "ANEA", {"COUNTRY": "JPN"}, limit=2)
    assert out["vintages"] == ["ANEA"]
    assert out["no_data"] == ["ANEA_2026_MAY_VINTAGE"]


def test_agreement_between_vintages_is_stated_not_left_as_an_empty_list(monkeypatch):
    """An empty "revisions" reads the same as a failed comparison otherwise."""
    monkeypatch.setattr(api, "dataflows", lambda p, q, n: {"shown": [
        {"id": i, "name": i} for i in ["X", "X_2026_JAN_VINTAGE", "X_2026_FEB_VINTAGE"]]})
    monkeypatch.setattr(api, "fetch", lambda *a, **k: {
        "series": [{"key": {}, "observations": [["2024", 1.0]]}]})
    out = vintages.compare("IMF_DATA", "X", {"COUNTRY": "JPN"})
    assert out["revisions"] == []
    assert "not revised" in out["note"]
