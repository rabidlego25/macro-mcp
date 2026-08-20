"""Currency conversion, from the ECB's own reference rates.

Three things about these rates are easy to get wrong and each is stated in the
response rather than left for the caller to assume.

**They are a fixing, not a spot rate.** The ECB publishes one set of reference
rates a day, based on a concertation procedure at 14:15 CET, on TARGET business
days only. Asking for a Sunday or a holiday returns the last day that was
published, and says which.

**Every rate is quoted against the euro.** The ECB publishes no USD/JPY rate.
Any pair that does not include EUR is a cross this module derives by dividing
two fixings, which is not a rate anyone traded; the response marks it
`derived`. A previous version of this file fetched such crosses from a
third-party service and labelled them "Daily ECB reference rate", which was
wrong twice over.

**Flows and stocks convert differently.** GDP or revenue converts at the period
average; debt or a balance sheet at end-of-period. Picking the wrong one shifts
the result by percent silently, so the convention is a required argument.

Rates come back through the same fetch path as every other series, so they
carry units, a range, and a bounded number of observations.
"""

from datetime import date, timedelta

from . import sdmx_api as api

PROVIDER = "ECB"
FLOW = "EXR"
EURO = "EUR"

# EXR publishes both conventions as separate series.
CONVENTIONS = {"average": "A", "end_of_period": "E"}

SOURCE = "ECB euro foreign exchange reference rates"
FIXING = "reference rate, 14:15 CET fixing on TARGET business days"

# Enough calendar to reach back over a long weekend or a national holiday.
LOOKBACK = 14


def _key(currencies: list[str], freq: str, suffix: str) -> dict:
    return {"FREQ": freq, "CURRENCY": "+".join(currencies),
            "CURRENCY_DENOM": EURO, "EXR_TYPE": "SP00", "EXR_SUFFIX": suffix}


def _series(out: dict) -> dict:
    """Observations per currency, from a response that hoists a single one."""
    hoisted = out.get("key", {}).get("CURRENCY")
    return {s["key"].get("CURRENCY", hoisted): dict(s["observations"])
            for s in out.get("series", [])}


def _check(code: str) -> str:
    c = str(code or "").strip().upper()
    if len(c) != 3 or not c.isalpha():
        raise ValueError(f"{code!r} is not a three-letter currency code")
    return c


def spot(base: str, quote: str, date_: str | None = None) -> dict:
    """One day's reference rate: how many units of `quote` buy one `base`.

    Omit the date for the most recent publication. A date that was not a TARGET
    business day returns the last one that was, named in "date".
    """
    base, quote = _check(base), _check(quote)
    if base == quote:
        raise ValueError(f"{base} and {quote} are the same currency")

    asked = date.fromisoformat(date_) if date_ else date.today()
    legs = [c for c in (base, quote) if c != EURO]
    out = api.fetch(PROVIDER, FLOW, _key(legs, "D", "A"),
                    str(asked - timedelta(days=LOOKBACK)), str(asked),
                    limit=LOOKBACK * len(legs))
    rates = _series(out)
    missing = [c for c in legs if not rates.get(c)]
    if missing:
        raise ValueError(
            f"ECB publishes no reference rate for {', '.join(missing)} in the "
            f"{LOOKBACK} days to {asked}")

    # Both legs have to come from the same fixing; a cross built from two dates
    # is not a rate that existed on either of them.
    common = sorted(set.intersection(*(set(rates[c]) for c in legs)))
    if not common:
        raise ValueError(f"no day in the {LOOKBACK} to {asked} carries both legs")
    on = common[-1]

    per_euro = {c: rates[c][on] for c in legs}
    rate = (per_euro[quote] if base == EURO else
            1 / per_euro[base] if quote == EURO else
            per_euro[quote] / per_euro[base])

    got = {"base": base, "quote": quote, "rate": rate, "date": on,
           "source": SOURCE, "convention": FIXING,
           "derived": EURO not in (base, quote)}
    if got["derived"]:
        got["note"] = (f"the ECB publishes no {base}/{quote} rate; this is "
                       f"{quote}/EUR divided by {base}/EUR on the same fixing")
    if date_ and on != date_:
        got["note_date"] = f"{date_} was not a publication day; {on} is the last before it"
    return got


def period_rate(currency: str, start: str, end: str, convention: str = "average",
                freq: str = "M", limit: int = 500) -> dict:
    """Euro reference rates by convention: "average" to convert flows,
    "end_of_period" for stocks.

    Returns the same shape as fetch_data — key, units, series, range — so a
    long daily range is bounded and labelled rather than returned whole.
    """
    currency = _check(currency)
    if convention not in CONVENTIONS:
        raise ValueError(
            f"convention must be one of {', '.join(CONVENTIONS)}, not {convention!r}; "
            "use average to convert a flow (GDP, revenue) and end_of_period for a "
            "stock (debt, balance sheet)")
    if currency == EURO:
        raise ValueError("EUR is the denominator of every ECB reference rate; "
                         "ask for the other side of the pair")

    out = api.fetch(PROVIDER, FLOW, _key([currency], freq, CONVENTIONS[convention]),
                    start, end, limit)
    return {"currency": currency, "denom": EURO, "convention": convention,
            "freq": freq, "source": SOURCE,
            "quoted": f"{currency} per EUR", **out}
