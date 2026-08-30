"""Language handling and fallbacks.

These are the paths that failed silently in practice: a wrong answer with a 200
status rather than an exception.
"""

import pytest
import requests
import sdmx

from conftest import parse, raw
from macro_mcp import bundesbank as bbk
from macro_mcp import sdmx_api as api


class Name:
    def __init__(self, loc):
        self.localizations = loc


class Obj:
    def __init__(self, loc, ident="X"):
        self.id, self.name = ident, Name(loc)


def test_names_drops_null_localizations():
    assert api._names(Obj({"en": None, "de": "Bilanz"})) == {"de": "Bilanz"}


def test_label_prefers_english_but_falls_back():
    assert api._label({"en": "Crops", "it": "Coltivazioni"}) == "Crops"
    assert api._label({"it": "Coltivazioni"}) == "Coltivazioni"
    assert api._label({}) == ""


def test_null_english_name_does_not_mask_the_german_one():
    """BBK publishes a null en name on some flows; it used to win over the real
    German label and crash search on None.lower()."""
    names = api._names(Obj({"en": None, "de": "Gewinn- und Verlustrechnung"}))
    assert api._label(names) == "Gewinn- und Verlustrechnung"
    assert api._matches("gewinn", "BBKRT", names)


def test_search_matches_across_localizations():
    names = {"en": "Crops", "it": "Coltivazioni"}
    assert api._matches("crops", "101_1015", names)
    assert api._matches("coltivazioni", "101_1015", names)
    assert api._matches("101", "101_1015", names)
    assert not api._matches("unemployment", "101_1015", names)


def test_bbk_dataflow_fixture_contains_a_null_english_name():
    """Pins the real-world case the fallback exists for."""
    flows = parse(bbk._repair(raw("bbk_dataflow.xml"))).dataflow
    nulls = {k: api._names(v) for k, v in flows.items()
             if (getattr(v.name, "localizations", None) or {}).get("en") is None}
    assert nulls, "fixture should still contain a flow with a null English name"
    assert all(api._label(n) for n in nulls.values()), "each must fall back to a real label"


def test_codes_falls_back_when_inline_codelist_is_empty(monkeypatch):
    sentinel = ["fetched"]
    monkeypatch.setattr(bbk, "codelist", lambda dim_id: sentinel)

    class Rep:
        enumerated = []          # present but empty, as BBK serves it

    class Dim:
        id, local_representation = "BBK_STD_FREQ", Rep()

    assert api._codes(Dim(), "BBK") is sentinel
    assert api._codes(Dim(), "ECB") == []      # other providers keep the empty list


def test_english_label_coverage_is_reported_only_when_incomplete(monkeypatch):
    codes = [Obj({"it": "Italia"}, "IT"), Obj({"en": "Germany"}, "DE")]

    class Dim:
        id = "GEO"

    class DSD:
        class dimensions:
            components = [Dim()]

    monkeypatch.setattr(api, "_dsd", lambda p, f: DSD)
    monkeypatch.setattr(api, "_supports", lambda p, r: True)

    monkeypatch.setattr(api, "_codes", lambda d, p=None: codes)
    partial = api.describe_flow("X", "F")["dimensions"][0]
    assert partial["english_labels"] == "1/2"
    assert partial["languages"] == ["en", "it"]

    monkeypatch.setattr(api, "_codes", lambda d, p=None: [Obj({"en": "Germany"}, "DE")])
    complete = api.describe_flow("X", "F")["dimensions"][0]
    assert "english_labels" not in complete


def test_fetch_retries_with_generic_sdmx_when_parsing_fails(monkeypatch):
    """BIS serves structure-specific data referencing a DSD sdmx1 cannot resolve."""
    calls = []

    class Client:
        def data(self, flow, key, params, headers=None):
            calls.append(headers)
            if headers is None:
                raise sdmx.exceptions.XMLParseError
            return message()

    monkeypatch.setattr(api, "_client", lambda p: Client())
    monkeypatch.setattr(api.sdmx, "to_pandas", lambda m: _frame())

    out = api.fetch("BIS", "WS_CBPOL", {"FREQ": "M"})
    assert out["total"] == 1
    assert len(calls) == 3  # the failed parse, the generic retry, the count check
    assert "genericdata" in calls[1]["Accept"]

    # The second fetch must not repeat the download that already failed once.
    # This assertion read == 2 before, which pinned a full wasted round trip
    # per BIS fetch as the specification.
    calls.clear()
    api.fetch("BIS", "WS_CBPOL", {"FREQ": "M"})
    assert len(calls) == 1
    assert "genericdata" in calls[0]["Accept"]


def _frame():
    import pandas as pd
    return pd.Series([1.0], index=pd.Index(["2024-01"], name="TIME_PERIOD"))


def message(obs: int = 1, series: int = 0):
    """A data message carrying `obs` observations across `series` series.

    Two counts are read outside to_pandas. The observation count tells a
    provider that ignored the download cap from a query that matched nothing.
    The series count tells a capped response that is whole from one that
    quietly left series out.
    """
    ds = type("DataSet", (), {"obs": [object()] * obs,
                              "series": {i: [object()] for i in range(series)}})()
    return type("Message", (), {"data": [ds]})()


class _Refusal(requests.HTTPError):
    """An HTTP error carrying a status, which is all _refused reads."""

    def __init__(self, status: int):
        super().__init__(f"{status}")
        self.response = type("Response", (), {"status_code": status})()


def _recorder(monkeypatch, answer):
    """Record the params of every data request and answer with `answer`."""
    seen = []

    class Client:
        def data(self, flow, key, params, headers=None):
            seen.append(dict(params))
            return answer(params)

    monkeypatch.setattr(api, "_client", lambda p: Client())
    monkeypatch.setattr(api.sdmx, "to_pandas", lambda m: _frame())
    return seen


def test_the_provider_is_asked_to_truncate_rather_than_shipping_the_history(monkeypatch):
    """`limit` bounded the response after the whole series had been downloaded
    and parsed — 4.9MB from ECB to answer a question about three days."""
    seen = _recorder(monkeypatch, lambda p: message())
    api.fetch("ECB", "EXR", {"FREQ": "D"}, limit=3)
    assert seen == [{"lastNObservations": 4}, {"detail": "nodata"}]


def test_the_cap_is_one_more_than_the_budget_so_truncation_stays_visible(monkeypatch):
    """Asked for exactly `limit`, a clipped series comes back the same length as
    a complete one and the response reports no truncation at all."""
    seen = _recorder(monkeypatch, lambda p: message())
    api.fetch("ECB", "EXR", {"FREQ": "D"}, limit=500)
    assert seen[0]["lastNObservations"] == 501


def test_the_cap_travels_with_the_period_bounds_rather_than_replacing_them(monkeypatch):
    seen = _recorder(monkeypatch, lambda p: message())
    api.fetch("ECB", "EXR", {"FREQ": "D"}, "2024-01", "2024-03", limit=3)
    assert seen[0] == {"startPeriod": "2024-01", "endPeriod": "2024-03",
                       "lastNObservations": 4}
    assert seen[1] == {"startPeriod": "2024-01", "endPeriod": "2024-03",
                       "detail": "nodata"}


def test_a_provider_that_rejects_the_cap_is_asked_again_without_it(monkeypatch):
    """Learned, not listed: no table can be right about a service nobody has
    asked. The refusal is a cheap error page, so guessing wrong costs little."""
    def answer(params):
        if "lastNObservations" in params:
            raise _Refusal(400)
        return message()

    seen = _recorder(monkeypatch, answer)
    out = api.fetch("X", "F", {}, limit=3)

    assert out["total"] == 1
    assert [p.get("lastNObservations") for p in seen] == [4, None]
    assert "X" in api._NO_LAST_N

    # And the refusal is not repeated for the life of the process.
    seen.clear()
    api.fetch("X", "F", {}, limit=3)
    assert seen == [{}]


def test_a_failing_service_is_not_mistaken_for_one_that_rejects_the_cap(monkeypatch):
    """A 5xx has already been retried in transport. Dropping the cap would not
    help, and remembering it would disable the cap for the whole process on the
    strength of one bad afternoon at ISTAT."""
    def answer(params):
        raise _Refusal(500)

    seen = _recorder(monkeypatch, answer)
    with pytest.raises(requests.HTTPError):
        api.fetch("ISTAT", "F", {}, limit=3)
    assert len(seen) == 1
    assert "ISTAT" not in api._NO_LAST_N


def test_a_cap_that_silently_empties_the_response_is_dropped_too(monkeypatch):
    """A service that answers 200 to a parameter it does not understand looks
    exactly like a query that matched nothing. Believing it would return an
    empty series as the answer to a question the provider can answer."""
    seen = _recorder(monkeypatch,
                     lambda p: message(0 if "lastNObservations" in p else 1))
    out = api.fetch("X", "F", {}, limit=3)

    assert out["total"] == 1
    assert [p.get("lastNObservations") for p in seen] == [4, None]
    assert "X" in api._NO_LAST_N


def test_a_query_that_matches_nothing_is_not_blamed_on_the_cap(monkeypatch):
    """Both requests come back empty, so the key is what is wrong. Recording the
    provider here would cost every later fetch its download bound."""
    import pandas as pd
    seen = _recorder(monkeypatch, lambda p: message(0))
    monkeypatch.setattr(api.sdmx, "to_pandas", lambda m: pd.Series(
        [], index=pd.Index([], name="TIME_PERIOD"), dtype=float))

    out = api.fetch("X", "F", {}, limit=3)
    assert out["total"] == 0
    assert "X" not in api._NO_LAST_N


def test_the_bundesbank_adapter_is_capped_on_the_same_terms(monkeypatch):
    """BBK is fetched outside sdmx1 but over the same REST parameter, and it is
    the flow with the widest key here — 5MB for one Bund yield."""
    seen = []

    def data(flow, key, params):
        seen.append(dict(params))
        return message()

    monkeypatch.setattr(api.bundesbank, "data", data)
    monkeypatch.setattr(api.sdmx, "to_pandas", lambda m: _frame())
    api.fetch("BBK", "BBSIS", {"BBK_STD_FREQ": "D"}, limit=2)
    assert seen == [{"lastNObservations": 3}, {"detail": "nodata"}]


def test_a_provider_that_drops_series_under_the_cap_is_asked_again_without_it(
        monkeypatch):
    """ILO answers a capped request for its US consumer price flow with 13
    series where 39 exist. The response has data, so the empty check waves it
    through, and nothing else in it shows that two thirds are missing: a
    provider is entitled to return fewer observations, and this one returns
    fewer series. Counting them another way is the only way to know."""
    seen = _recorder(monkeypatch, lambda p: message(
        obs=1, series=13 if "lastNObservations" in p else 39))
    api.fetch("ILO", "DF_CPI", {"REF_AREA": "USA"}, limit=3)

    assert [("lastNObservations" in p, p.get("detail")) for p in seen] == [
        (True, None),      # capped, and it looks fine
        (False, "nodata"), # the keys, which say 39 exist
        (False, None)]     # so fetch it properly
    assert api._NO_LAST_N == {"ILO"} and api._KEEPS_SERIES == {}


def test_a_provider_that_keeps_every_series_is_checked_once_and_then_trusted(
        monkeypatch):
    """The check costs a request, so it must not cost one per fetch."""
    seen = _recorder(monkeypatch, lambda p: message(obs=1, series=4))
    api.fetch("ECB", "EXR", {"FREQ": "D"}, limit=3)
    assert len(seen) == 2 and api._KEEPS_SERIES == {"ECB": 4}

    seen.clear()
    api.fetch("ECB", "EXR", {"FREQ": "D"}, limit=3)
    assert seen == [{"lastNObservations": 4}]


def test_a_smaller_cap_than_the_one_verified_is_checked_again(monkeypatch):
    """ILO returns 39 series when asked for 2001 observations and 13 when asked
    for 501, so a verdict is only good for the number it was measured at and
    anything larger. Recorded as a plain yes, one fetch at limit=2000 would
    certify a provider that drops two thirds of its series at the default."""
    seen = _recorder(monkeypatch, lambda p: message(obs=1, series=4))
    api.fetch("ECB", "EXR", {"FREQ": "D"}, limit=500)
    assert api._KEEPS_SERIES == {"ECB": 501}

    seen.clear()
    api.fetch("ECB", "EXR", {"FREQ": "D"}, limit=1000)   # larger, so trusted
    assert seen == [{"lastNObservations": 1001}]

    seen.clear()
    api.fetch("ECB", "EXR", {"FREQ": "D"}, limit=3)      # smaller, so measured
    assert seen == [{"lastNObservations": 4}, {"detail": "nodata"}]
    assert api._KEEPS_SERIES == {"ECB": 4}


def test_a_provider_that_cannot_answer_the_count_is_not_given_the_benefit(
        monkeypatch):
    """Assuming the capped answer is whole is the assumption that lost ILO its
    series, so a provider that refuses the check loses the cap instead."""
    def answer(params):
        if params.get("detail") == "nodata":
            raise _Refusal(400)
        return message(obs=1, series=4)

    seen = _recorder(monkeypatch, answer)
    api.fetch("ECB", "EXR", {"FREQ": "D"}, limit=3)
    assert api._NO_LAST_N == {"ECB"}
    assert seen[-1] == {}, "the uncapped fetch it fell back to"
