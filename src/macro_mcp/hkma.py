"""Hong Kong Monetary Authority adapter.

Free and keyless, but not SDMX and with no catalogue endpoint, so the table
below was taken from the published documentation and then verified one request
at a time against the live API. Of the 156 endpoints the docs advertise, 125
answer with observations; the rest are section indexes or reference tables.

Each endpoint returns one wide row per period — 78 columns on the balance
sheets — so a column becomes a code of a single SERIES dimension, the same
shape Singapore's rows take.

The date range is the trap. `from` and `to` are accepted and silently ignored
unless `choose` names the period column: ten days of January 2024 requested
without it comes back as five thousand rows reaching to 2006, with a 200. With
it, the comparison is literal, so a bound coarser than the period it is matched
against selects nothing at all. Both failures are answered here by filtering
what arrives rather than trusting the query.
"""

import pandas as pd
from functools import lru_cache

from . import cache

BASE = "https://api.hkma.gov.hk/public/market-data-and-statistics"
DIMENSION = "SERIES"

# The longest history on offer is 6302 daily rows, so one request always covers
# a whole endpoint and there is no paging to do.
PAGESIZE = 20000

FREQUENCY = {"end_of_date": "Daily", "end_of_day": "Daily",
             "end_of_month": "Monthly", "end_of_quarter": "Quarterly",
             "end_of_year": "Annual"}

SECTIONS = {
    "daily-monetary-statistics": (
        "daily-figures-interbank-liquidity", "daily-figures-monetary-base",
        "usage-rmb-liquidity-fac",
    ),
    "monthly-statistical-bulletin/banking": (
        "assetquality-ais", "assetquality-retailbanks", "balance-sheet-ais",
        "balance-sheet-dtc", "balance-sheet-lb", "balance-sheet-rlb", "capital-adequacy",
        "ch-statistics-ch-turnover", "ch-statistics-fps-reg",
        "ch-statistics-turnover-fps-hkd-payment-val",
        "ch-statistics-turnover-fps-hkd-payment-vol",
        "ch-statistics-turnover-fps-rmb-payment-val",
        "ch-statistics-turnover-fps-rmb-payment-vol", "credit-card-lending-survey",
        "customer-deposits-by-currency", "customer-deposits-by-type-cny",
        "customer-deposits-by-type-hkd-fc", "elc-endperiod", "elc-pos-v-all",
        "elc-pos-v-jp", "elc-pos-v-mc", "elc-pos-v-sin", "elc-pos-v-uk", "elc-pos-v-us",
        "fc-position-all", "fc-position-cad", "fc-position-chf", "fc-position-dem",
        "fc-position-eur", "fc-position-gbp", "fc-position-jpy", "fc-position-other",
        "fc-position-usd", "liquidity", "loans-by-sector-ais", "loans-by-sector-dtc",
        "loans-by-sector-lb", "loans-by-sector-rlb", "loans-by-type-ais",
        "loans-by-type-dtc", "loans-by-type-lb", "loans-by-type-rlb", "mr-lending",
        "mr-lending-ais-type", "mr-lending-borrowers-type", "number-of-ais-lros",
        "other-mr-non-bank-exposures", "residential-mortgage-loans-neg-equity",
        "residential-mortgage-survey",
    ),
    "monthly-statistical-bulletin/ef-fc-resv-assets": (
        "analysis-fc-reserve-assets", "currency-board-account",
        "data-intreserve-fcliquidity", "ef-analyt-acct", "ef-bal-sheet-abridged",
        "ef-bal-sheet-half-yearly-efbs", "fc-resv-assests",
    ),
    "monthly-statistical-bulletin/efbn": (
        "cmu-outstanding-remain-tenor-all-currencies", "cmu-outstanding-remain-tenor-hkd",
        "cmu-outstanding-remain-tenor-other-fc", "cmu-outstanding-remain-tenor-rmb",
        "cmu-outstanding-remain-tenor-usd", "cmu-service",
        "cmu-turnover-sec-mkt-remain-tenor-all-currencies",
        "cmu-turnover-sec-mkt-remain-tenor-hkd",
        "cmu-turnover-sec-mkt-remain-tenor-other-fc",
        "cmu-turnover-sec-mkt-remain-tenor-rmb", "cmu-turnover-sec-mkt-remain-tenor-usd",
        "efbn-oustanding-original-maturity", "efbn-outstanding-remaining-tenor",
        "efbn-turnover-sec-mkt-original-maturity", "efbn-turnover-sec-mkt-remaining-tenor",
        "efbn-yield-daily", "efbn-yield-endperiod", "efbn-yield-periodaverage",
    ),
    "monthly-statistical-bulletin/er-ir": (
        "composite-ir", "er-eeri-daily", "er-eeri-endperiod", "er-eeri-periodaverage",
        "hk-interbank-ir-daily", "hk-interbank-ir-endperiod",
        "hk-interbank-ir-periodaverage", "hkd-fer-daily", "hkd-fer-endperiod",
        "hkd-fer-periodaverage", "hkd-ir-periodaverage", "renminbi-dr",
    ),
    "monthly-statistical-bulletin/financial": (
        "banking-statistics", "capital-market-statistics", "economic-statistics",
        "monetary-statistics",
    ),
    "monthly-statistical-bulletin/gov-bond": (
        "new-issuance-amt-gov-bonds", "out-amt-gov-bonds-original-maturity",
        "out-amt-gov-bonds-remaining-tenor",
        "sec-mar-turnover-govbonds-ibip-original-maturity",
        "sec-mar-turnover-govbonds-ibip-remain-tenor",
    ),
    "monthly-statistical-bulletin/ibpgsbp": (
        "new-issuance-amt-gov-bonds-ibpgsbp-hkd", "new-issuance-amt-gov-bonds-ibpgsbp-rmb",
        "sec-mar-turnover-govbonds-ibpgsbp-original-maturity-hkd",
        "sec-mar-turnover-govbonds-ibpgsbp-original-maturity-rmb",
        "sec-mar-turnover-govbonds-ibpgsbp-remaining-maturity-hkd",
        "sec-mar-turnover-govbonds-ibpgsbp-remaining-maturity-rmb",
    ),
    "monthly-statistical-bulletin/monetary-operation": (
        "disc-win-liquid-adj-win-rates-daily", "disc-win-liquid-adj-win-rates-endperiod",
        "disc-win-liquid-adj-win-rates-periodaverage", "market-operation-daily",
        "market-operation-periodaverage", "monetary-base-daily", "monetary-base-endperiod",
    ),
    "monthly-statistical-bulletin/money": (
        "components-seasonally-adjusted-hkd", "currency", "supply-adjusted",
        "supply-components-all", "supply-components-fc", "supply-components-hkd",
        "supply-unadjusted-fc",
    ),
    "monthly-statistical-bulletin/money-markets": (
        "hkd-interbank-trans", "liab-dt-other-ais", "ncds-issued-in-hk",
        "ni-hkd-debt-inst-oth-efbn", "osamt-hkd-debtinst-otherthan-efbn",
        "turnover-ncds-sec-mar-hk-ais",
    ),
    "other": (
        "ef-operating-expenses",
    ),
}

FLOWS = {slug: section for section, slugs in SECTIONS.items() for slug in slugs}


def _get(flow: str, params: dict) -> list[dict]:
    if flow not in FLOWS:
        raise ValueError(f"no HKMA dataset {flow}; find_dataflows lists them")
    r = cache.session().get(f"{BASE}/{FLOWS[flow]}/{flow}", params=params,
                            timeout=cache.TIMEOUT)
    if r.status_code == 404:
        # The table below is a snapshot of a catalogue HKMA does not publish, so
        # it goes stale as datasets are retired. Say which one and how to fix it
        # rather than surface a bare 404 from a URL the agent never composed.
        raise RuntimeError(
            f"HKMA no longer serves {flow}; regenerate the dataset table with "
            "`uv run python -m scripts.hkma_catalogue`")
    r.raise_for_status()
    body = r.json()
    head = body.get("header") or {}
    if not head.get("success"):
        raise RuntimeError(f"HKMA refused {flow}: {head.get('err_msg', 'unknown error')}")
    return (body.get("result") or {}).get("records") or []


@lru_cache(maxsize=64)
def _columns(flow: str) -> tuple[str, int, tuple[str, ...]]:
    """The period column, how wide its values are, and the value columns.

    All three are read from one row. HKMA names the period differently per
    endpoint — end_of_date, end_of_month, end_of_quarter — and writes it at
    matching precision, so both are measured rather than assumed.
    """
    rows = _get(flow, {"pagesize": 1})
    if not rows:
        return "", 0, ()
    keys = list(rows[0])
    period = next((k for k in keys if k.startswith("end_of")), keys[0])
    return period, len(str(rows[0][period])), tuple(k for k in keys if k != period)


def _within(period: str, start: str | None, end: str | None) -> bool:
    """Compared on a prefix, so end="2024" keeps every month of 2024."""
    return ((not start or period[:len(start)] >= start)
            and (not end or period[:len(end)] <= end))


def dataflows(search: str | None = None, limit: int = 40) -> dict:
    ids = sorted(FLOWS)
    if search:
        q = search.lower()
        ids = [f for f in ids if q in f or q in f.replace("-", " ")]
    return {"total": len(ids),
            "shown": [{"id": f, "name": f.replace("-", " ")} for f in ids[:limit]]}


def describe(flow: str) -> dict:
    if flow not in FLOWS:
        return {"error": f"no HKMA dataset {flow}; search find_dataflows for one"}
    period, _, fields = _columns(flow)
    return {"provider": "HKMA", "flow": flow,
            "frequency": FREQUENCY.get(period, "unknown"),
            "dimensions": [{"id": DIMENSION, "codes": len(fields),
                            "sample": [{"id": f, "name": f.replace("_", " ")}
                                       for f in fields[:8]]}],
            "note": "one column per series; join several with SERIES=a+b"}


def codes(flow: str, dimension: str, query: str = "", limit: int = 30) -> dict:
    if dimension.upper() != DIMENSION:
        return {"error": f"HKMA datasets have one dimension, {DIMENSION}"}
    q = query.lower()
    hits = [{"id": f, "name": f.replace("_", " ")} for f in _columns(flow)[2]
            if not q or q in f.replace("_", " ")]
    return {"total": len(hits), "shown": hits[:limit]}


def frame(flow: str, key: dict, start: str | None = None, end: str | None = None):
    period, width, fields = _columns(flow)
    wanted = [s for s in str(key.get(DIMENSION, "")).split("+") if s] or list(fields)
    unknown = [s for s in wanted if s not in fields]
    if unknown:
        raise ValueError(f"no series {unknown} in {flow}; search_codes lists them")

    # Only a bound as precise as the period itself is worth sending: the service
    # compares the two literally, so from=2024 against 2024-03 matches nothing.
    # Anything coarser is left to the filter below. `choose` names the column
    # the bounds apply to; without it they are ignored, and without them it is
    # a 400, so all three travel together or none do.
    params = {"pagesize": PAGESIZE}
    bounds = {k: v for k, v in (("from", start), ("to", end)) if v and len(v) == width}
    if bounds:
        params.update(bounds, choose=period)

    rows = [{DIMENSION: f, "TIME_PERIOD": r[period], "value": r.get(f)}
            for r in _get(flow, params) if _within(str(r[period]), start, end)
            for f in wanted]
    df = pd.DataFrame(rows, columns=[DIMENSION, "TIME_PERIOD", "value"])
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    return df
