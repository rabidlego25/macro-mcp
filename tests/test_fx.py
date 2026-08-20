"""Rate conventions, and the two ways an FX number lies quietly.

The first is the convention: converting a flow at an end-of-period rate is
wrong by percent and raises nothing. The second is provenance — the ECB
publishes no USD/JPY rate, so any such number is a cross somebody derived, and
returning it as an "ECB reference rate" is a wrong answer with a 200 attached.
"""

import pytest

from macro_mcp import fx


@pytest.fixture
def ecb(monkeypatch):
    """Serve EXR from a table instead of the network."""
    def install(table: dict, hoist_single=True):
        def fake(provider, flow, key, start=None, end=None, limit=500):
            assert (provider, flow) == ("ECB", "EXR")
            wanted = str(key["CURRENCY"]).split("+")
            series = [{"key": {"CURRENCY": c}, "observations":
                       [[p, v] for p, v in sorted(table[c].items())]}
                      for c in wanted if c in table]
            out = {"key": dict(key), "series": series, "columns": ["period", "value"]}
            if hoist_single and len(series) == 1:
                # fetch hoists an invariant dimension, so a single-currency
                # response carries no CURRENCY on the series at all.
                out["series"] = [{"key": {}, "observations": series[0]["observations"]}]
            else:
                out["key"].pop("CURRENCY", None)
            return out
        monkeypatch.setattr(fx.api, "fetch", fake)
    return install


# --- conventions -------------------------------------------------------------

def test_an_unknown_convention_says_which_ones_exist_and_what_they_are_for():
    """It was a bare dict subscript, so the agent saw KeyError: 'avg'."""
    with pytest.raises(ValueError) as e:
        fx.period_rate("USD", "2024-01", "2024-03", "avg")
    assert "average" in str(e.value) and "end_of_period" in str(e.value)
    assert "flow" in str(e.value) and "stock" in str(e.value)


def test_the_two_conventions_read_different_series(monkeypatch):
    seen = []

    def fake(provider, flow, key, start=None, end=None, limit=500):
        seen.append(key["EXR_SUFFIX"])
        return {"key": {}, "series": [], "columns": ["period", "value"]}

    monkeypatch.setattr(fx.api, "fetch", fake)
    fx.period_rate("JPY", "2024-01", "2024-01", "average")
    fx.period_rate("JPY", "2024-01", "2024-01", "end_of_period")
    assert seen == ["A", "E"]


def test_asking_for_euros_per_euro_is_refused():
    with pytest.raises(ValueError, match="denominator"):
        fx.period_rate("EUR", "2024-01", "2024-03")


def test_period_rates_come_back_in_the_shared_response_shape(ecb):
    """It used to return a flat dict of every period with no bound: 27 years of
    daily rates was 7,137 entries and 156KB, in a server whose headline is 6KB."""
    ecb({"JPY": {"2024-01": 159.45, "2024-02": 161.37}})
    out = fx.period_rate("JPY", "2024-01", "2024-02", "average")
    assert out["convention"] == "average"
    assert out["quoted"] == "JPY per EUR"
    assert out["series"][0]["observations"] == [["2024-01", 159.45], ["2024-02", 161.37]]
    assert "rates" not in out  # the old unbounded shape


# --- spot --------------------------------------------------------------------

def test_a_euro_pair_is_reported_as_published(ecb):
    ecb({"USD": {"2024-01-05": 1.0921}})
    got = fx.spot("EUR", "USD", "2024-01-05")
    assert got["rate"] == pytest.approx(1.0921)
    assert got["derived"] is False
    assert "fixing" in got["convention"]


def test_the_other_direction_is_the_reciprocal(ecb):
    ecb({"USD": {"2024-01-05": 1.0921}})
    assert fx.spot("USD", "EUR", "2024-01-05")["rate"] == pytest.approx(1 / 1.0921)


def test_a_pair_without_the_euro_is_marked_derived_and_explained(ecb):
    """The ECB publishes no USD/JPY. Returning one unlabelled as an ECB
    reference rate is the silent-wrong-answer case this repo is about."""
    ecb({"USD": {"2024-01-05": 1.0921}, "JPY": {"2024-01-05": 158.35}})
    got = fx.spot("USD", "JPY", "2024-01-05")
    assert got["rate"] == pytest.approx(158.35 / 1.0921)
    assert got["derived"] is True
    assert "publishes no USD/JPY" in got["note"]


def test_both_legs_must_come_from_the_same_fixing(ecb):
    """A cross built from two different days is a rate that existed on neither."""
    ecb({"USD": {"2024-01-04": 1.09, "2024-01-05": 1.0921},
         "JPY": {"2024-01-04": 158.0}})
    got = fx.spot("USD", "JPY", "2024-01-05")
    assert got["date"] == "2024-01-04"
    assert got["rate"] == pytest.approx(158.0 / 1.09)


def test_a_closed_day_returns_the_last_publication_and_says_so(ecb):
    """2024-01-06 was a Saturday. Reference rates are TARGET business days."""
    ecb({"USD": {"2024-01-05": 1.0921}})
    got = fx.spot("EUR", "USD", "2024-01-06")
    assert got["date"] == "2024-01-05"
    assert "not a publication day" in got["note_date"]


def test_a_currency_the_ecb_does_not_publish_says_that(ecb):
    ecb({"USD": {"2024-01-05": 1.0921}})
    with pytest.raises(ValueError, match="no reference rate for XYZ"):
        fx.spot("EUR", "XYZ", "2024-01-05")


@pytest.mark.parametrize("bad", ["US", "usdd", "", "12A"])
def test_a_malformed_currency_code_is_rejected_before_the_request(bad):
    with pytest.raises(ValueError, match="three-letter"):
        fx.spot("EUR", bad)


def test_a_pair_of_the_same_currency_is_refused():
    with pytest.raises(ValueError, match="same currency"):
        fx.spot("USD", "usd")
