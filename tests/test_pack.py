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


def test_a_response_with_no_observations_stays_well_formed():
    out = _pack(frame([("M", "2024-01", float("nan"))]), 500)
    assert out == {"key": {}, "columns": ["period", "value"], "series": [],
                   "total": 0, "empty": 1}


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
