"""Currency conversion, with the average/end-of-period distinction made explicit.

Comparing figures across countries needs both a base currency and a rate
convention. Flows (GDP, revenue) convert at the period average; stocks (debt,
balance sheet) convert at end-of-period. Picking the wrong one silently shifts
results by percent, so the choice is a required argument.
"""

import httpx

import sdmx

FRANKFURTER = "https://api.frankfurter.dev/v1"


def spot(base: str, quote: str, date: str | None = None) -> dict:
    """Daily ECB reference rate. Free, no key, 30+ currencies."""
    r = httpx.get(f"{FRANKFURTER}/{date or 'latest'}",
                  params={"base": base.upper(), "symbols": quote.upper()}, timeout=30)
    r.raise_for_status()
    d = r.json()
    return {"base": d["base"], "quote": quote.upper(),
            "rate": d["rates"][quote.upper()], "date": d["date"], "convention": "daily spot"}


def period_rate(currency: str, start: str, end: str, convention: str = "average",
                freq: str = "M") -> dict:
    """EUR-based rates from the ECB EXR flow, which publishes both conventions.

    convention: "average" for flows, "end_of_period" for stocks.
    """
    suffix = {"average": "A", "end_of_period": "E"}[convention]
    msg = sdmx.Client("ECB").data(
        "EXR",
        key={"FREQ": freq, "CURRENCY": currency.upper(), "CURRENCY_DENOM": "EUR",
             "EXR_TYPE": "SP00", "EXR_SUFFIX": suffix},
        params={"startPeriod": start, "endPeriod": end},
    )
    s = sdmx.to_pandas(msg)
    rates = {str(k[-1]): float(v) for k, v in s.items()}
    return {"currency": currency.upper(), "denom": "EUR", "convention": convention,
            "freq": freq, "rates": rates}
