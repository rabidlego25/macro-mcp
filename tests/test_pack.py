"""Response shape.

The flat frame repeated the whole key on every row, emitted bare NaN (which no
strict JSON parser accepts) and truncated to the oldest rows while reporting
only a total, so a clipped window looked like a complete one.
"""

import json

import pandas as pd
import pytest

from macro_mcp.sdmx_api import _pack


def frame(rows, dims=("FREQ",)):
    return pd.DataFrame(rows, columns=[*dims, "TIME_PERIOD", "value"])


def test_invariant_dimensions_are_hoisted_out_of_the_observations():
    out = _pack(frame([("M", "2024-01", 1.0), ("M", "2024-02", 2.0)]), 500)
    assert out["key"] == {"FREQ": "M"}
    assert out["series"] == [{"key": {}, "observations": [["2024-01", 1.0],
                                                         ["2024-02", 2.0]]}]
    assert "FREQ" not in json.dumps(out["series"])


def test_varying_dimensions_become_series_instead_of_repeating_per_row():
    df = frame([("M", "JP", "2024-01", -0.1), ("M", "JP", "2024-02", -0.1),
                ("M", "US", "2024-01", 5.5), ("M", "US", "2024-02", 5.5)],
               dims=("FREQ", "REF_AREA"))
    out = _pack(df, 500)
    assert out["key"] == {"FREQ": "M"}  # invariant hoisted
    assert [s["key"] for s in out["series"]] == [{"REF_AREA": "JP"}, {"REF_AREA": "US"}]
    assert out["series"][1]["observations"] == [["2024-01", 5.5], ["2024-02", 5.5]]


def test_empty_observations_are_dropped_counted_and_never_serialised_as_nan():
    df = frame([("D", "2024-01-01", float("nan")), ("D", "2024-01-02", 2.13),
                ("D", "2024-01-06", float("nan")), ("D", "2024-01-03", 2.10)])
    out = _pack(df, 500)
    assert out["total"] == 2
    assert out["empty"] == 2
    assert out["series"][0]["observations"] == [["2024-01-02", 2.13], ["2024-01-03", 2.10]]

    payload = json.dumps(out)
    assert "NaN" not in payload
    json.loads(payload, parse_constant=lambda c: pytest.fail(f"non-JSON token {c}"))


def test_truncation_keeps_the_most_recent_rows_and_says_so():
    """head() returned the oldest rows, so a request for the latest value got a
    plausible answer from the far end of the series with nothing flagging it."""
    df = frame([("M", f"2024-{m:02d}", float(m)) for m in range(1, 13)])
    out = _pack(df, 3)
    assert out["total"] == 12
    assert out["range"] == ["2024-10", "2024-12"]
    assert out["series"][0]["observations"] == [["2024-10", 10.0], ["2024-11", 11.0],
                                                ["2024-12", 12.0]]
    assert "most recent 3 of 12" in out["truncated"]


def test_untruncated_responses_report_their_span_and_no_truncation_flag():
    out = _pack(frame([("M", "2024-01", 1.0), ("M", "2024-03", 3.0)]), 500)
    assert out["range"] == ["2024-01", "2024-03"]
    assert "truncated" not in out and "empty" not in out


def test_a_response_whose_observations_are_all_empty_says_which_case_it_is():
    """The key matched and the values are missing, which is not the same as a
    key that matched nothing. Both used to be an empty series list."""
    out = _pack(frame([("M", "2024-01", float("nan"))]), 500, asked={"FREQ": "M"})
    assert out["series"] == [] and out["total"] == 0 and out["empty"] == 1
    assert out["note"] == "the key matched, but every observation in the period is empty."


def test_a_key_that_matched_nothing_is_echoed_back_with_what_to_try():
    """Found by an eval. A wrong code, an aggregate carrying no such series and
    one empty code in a multi-code key all returned the same four fields, and
    none of them named the key that had just failed: hoisting reads the key off
    the frame, and an empty frame has no columns."""
    out = _pack(frame([], dims=("COUNTRY",)), 500,
                asked={"COUNTRY": "G998", "INDICATOR": "B1GQ"})
    assert out["key"] == {"COUNTRY": "G998", "INDICATOR": "B1GQ"}
    assert out["total"] == 0 and "empty" not in out
    assert "Leave a dimension out of the key" in out["note"]


def test_codes_are_returned_with_the_labels_the_response_already_knows():
    """Also from an eval. TYPE_OF_TRANSFORMATION: XDC is where the currency of
    a 15-digit number lives, and it arrived unexplained."""
    df = frame([("M", "JP", "2024-01", 1.0), ("M", "US", "2024-02", 2.0)],
               dims=("FREQ", "REF_AREA"))
    out = _pack(df, 500, names={"FREQ": {"M": "Monthly", "A": "Annual"},
                                "REF_AREA": {"JP": "Japan", "US": "United States",
                                             "DE": "Germany"}})
    assert out["names"] == {"FREQ": {"M": "Monthly"},
                            "REF_AREA": {"JP": "Japan", "US": "United States"}}


def test_only_the_codes_that_appear_are_named():
    """A codelist can run to hundreds of entries. Returning it whole is the
    thing describe_flow exists to avoid."""
    out = _pack(frame([("M", "2024-01", 1.0)]), 500,
                names={"FREQ": {c: c for c in "MQADWH"}})
    assert out["names"] == {"FREQ": {"M": "M"}}


def test_packing_a_wide_key_is_an_order_of_magnitude_smaller():
    """Shaped like BBSIS, the flow that motivated this: 15 invariant dimensions
    against a year of daily observations."""
    dims = tuple(f"BBK_SEIS_D{i}" for i in range(15))
    days = pd.date_range("2024-01-01", "2024-12-31").strftime("%Y-%m-%d")
    df = pd.DataFrame([(*["S1311"] * 15, d, 2.13) for d in days],
                      columns=[*dims, "TIME_PERIOD", "value"])

    flat = len(json.dumps({"total": len(df), "records": df.to_dict("records")}))
    packed = len(json.dumps(_pack(df, 500)))
    assert packed * 10 < flat, f"{flat} -> {packed}"


def test_imf_month_notation_is_rewritten_so_periods_join():
    """IMF writes 2024-M01. It parses and sorts perfectly well, which is the
    problem: a series in its own notation joins against nothing."""
    out = _pack(frame([("M", "2024-M01", 1.0), ("M", "2024-M02", 2.0)]), 500)
    assert [p for p, _ in out["series"][0]["observations"]] == ["2024-01", "2024-02"]
    assert out["range"] == ["2024-01", "2024-02"]


def test_annual_and_quarterly_periods_are_left_alone():
    """Only the month infix is non-standard; rewriting more would corrupt."""
    out = _pack(frame([("Q", "2024-Q1", 1.0), ("Q", "2024-Q2", 2.0)]), 500)
    assert [p for p, _ in out["series"][0]["observations"]] == ["2024-Q1", "2024-Q2"]


def test_truncation_shares_the_budget_out_rather_than_deleting_a_whole_series():
    """The budget was spent oldest-first across the whole response, so the older
    series vanished — and with it gone, REF_AREA was invariant and got hoisted,
    leaving a response that read as though only US had ever been asked for."""
    df = frame([("M", "JP", f"2023-{m:02d}", float(m)) for m in range(1, 13)] +
               [("M", "US", f"2024-{m:02d}", float(m)) for m in range(1, 13)],
               dims=("FREQ", "REF_AREA"))
    out = _pack(df, 4)

    assert out["key"] == {"FREQ": "M"}
    assert "REF_AREA" not in out["key"]
    assert [s["key"] for s in out["series"]] == [{"REF_AREA": "JP"}, {"REF_AREA": "US"}]
    assert out["series"][0]["observations"] == [["2023-11", 11.0], ["2023-12", 12.0]]
    assert out["series"][1]["observations"] == [["2024-11", 11.0], ["2024-12", 12.0]]
    assert out["range"] == ["2023-11", "2024-12"]
    assert out["total"] == 24
    assert "most recent 4 of 24, at most 2 per series" in out["truncated"]


def test_a_dimension_that_only_truncation_made_invariant_is_not_hoisted():
    """One series is short enough to survive whole; the other is clipped to
    nothing under the old rule. Hoisting is decided on the frame as asked for."""
    df = frame([("M", "JP", "2023-01", 1.0),
                ("M", "US", "2024-01", 2.0), ("M", "US", "2024-02", 3.0)],
               dims=("FREQ", "REF_AREA"))
    out = _pack(df, 2)
    assert out["key"] == {"FREQ": "M"}
    assert [s["key"] for s in out["series"]] == [{"REF_AREA": "JP"}, {"REF_AREA": "US"}]


def test_more_series_than_budget_names_what_it_dropped_instead_of_hiding_it():
    df = frame([("M", f"C{i}", "2024-01", float(i)) for i in range(5)],
               dims=("FREQ", "REF_AREA"))
    out = _pack(df, 3)
    assert [s["key"]["REF_AREA"] for s in out["series"]] == ["C0", "C1", "C2"]
    assert out["dropped_series"] == {"count": 2, "keys": [{"REF_AREA": "C3"},
                                                          {"REF_AREA": "C4"}]}
    assert out["total"] == 5


def test_every_series_keeps_at_least_one_observation_when_the_budget_is_tight():
    """Two series and a budget of two: one observation each, not both from one."""
    df = frame([("M", "JP", f"2024-{m:02d}", float(m)) for m in range(1, 13)] +
               [("M", "US", f"2024-{m:02d}", float(m)) for m in range(1, 13)],
               dims=("FREQ", "REF_AREA"))
    out = _pack(df, 2)
    assert [s["observations"] for s in out["series"]] == [[["2024-12", 12.0]]] * 2
    assert "dropped_series" not in out


def test_a_budget_smaller_than_the_series_count_drops_rather_than_overshoots():
    """`limit` stays a hard bound on observations, so two series cannot both be
    served under a budget of one. The one left out is named."""
    df = frame([("M", "JP", "2024-01", 1.0), ("M", "US", "2024-01", 2.0)],
               dims=("FREQ", "REF_AREA"))
    out = _pack(df, 1)
    assert [s["key"] for s in out["series"]] == [{"REF_AREA": "JP"}]
    assert out["dropped_series"] == {"count": 1, "keys": [{"REF_AREA": "US"}]}


def test_a_short_series_lends_its_unused_share_to_a_long_one():
    """An even split clipped a 400-observation series to 250 under limit=500
    because a 10-observation series held the other half of a budget it could
    not use — truncating a response that would have fitted whole."""
    df = frame([("M", "JP", f"{2000 + m // 12}-{m % 12 + 1:02d}", float(m))
                for m in range(400)] +
               [("M", "US", f"2024-{m:02d}", float(m)) for m in range(1, 11)],
               dims=("FREQ", "REF_AREA"))
    out = _pack(df, 500)
    assert [len(s["observations"]) for s in out["series"]] == [400, 10]
    assert "truncated" not in out
    assert out["total"] == 410


def test_a_series_that_arrives_at_the_cap_reports_total_as_a_floor():
    """The provider was asked for four and sent four, so there is a fifth it was
    not asked for. `total` is no longer the length of the series, and a response
    that said "of 4" would read as though it were."""
    df = frame([("M", f"2024-{m:02d}", float(m)) for m in range(1, 5)])
    out = _pack(df, 3, cap=4)
    assert out["total"] == 4
    assert "most recent 3 of at least 4" in out["truncated"]
    assert "total is a floor" in out["truncated"]


def test_a_series_that_arrives_short_of_the_cap_is_counted_exactly():
    """Three back from a request for four is the whole series, and saying so is
    the reason the cap is limit + 1 rather than limit."""
    df = frame([("M", f"2024-{m:02d}", float(m)) for m in range(1, 4)])
    out = _pack(df, 3, cap=4)
    assert out["total"] == 3
    assert "truncated" not in out


def test_the_cap_counts_the_empty_observations_the_provider_counted():
    """Two of the four sent carry no value. Measuring the cap against the two
    that survived would read a clipped series as a complete one."""
    df = frame([("D", "2024-01-01", float("nan")), ("D", "2024-01-02", 1.0),
                ("D", "2024-01-03", float("nan")), ("D", "2024-01-04", 2.0)])
    out = _pack(df, 3, cap=4)
    assert out["total"] == 2 and out["empty"] == 2
    assert "most recent 2 of at least 2" in out["truncated"]


def test_the_cap_is_per_series_so_one_long_series_makes_the_total_a_floor():
    """lastNObservations bounds each series, not the response. JP came back at
    the cap and US came back whole; the total covers both, so it is a floor."""
    df = frame([("M", "JP", f"2024-{m:02d}", float(m)) for m in range(1, 5)] +
               [("M", "US", "2024-01", 1.0)], dims=("FREQ", "REF_AREA"))
    out = _pack(df, 3, cap=4)
    assert "most recent 3 of at least 5, at most 2 per series" in out["truncated"]
