"""Singapore Department of Statistics, via the Table Builder API.

Keyless JSON rather than SDMX, but the shape maps onto the same grammar: a
table is a dataflow, its rows are the codes of a single SERIES dimension, and
each row's columns are the observations.

Periods arrive as "1961 Jan" and "1961 1Q", which are neither ISO nor sortable
(Apr precedes Jan alphabetically). They are rewritten to SDMX form so Singapore
joins against the other providers instead of sitting in its own notation.
"""

import re
from functools import lru_cache

import pandas as pd

from . import cache

BASE = "https://tablebuilder.singstat.gov.sg/api/table"
DIMENSION = "SERIES"

# Singapore states the unit per row, in the same payload the observations come
# from. Read for search_codes since the beginning and dropped on the way to the
# frame, which made this the one provider whose unit was in hand and discarded.
UNIT = "UNIT"
UNITS = (UNIT,)

MONTHS = {m: f"{i:02d}" for i, m in enumerate(
    "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(), 1)}

_PERIOD = re.compile(r"(\d{4})(?:\s+(\S+))?")


def period(key: str) -> str:
    """"1961 Jan" -> "1961-01", "1961 1Q" -> "1961-Q1", "1961 1H" -> "1961-S1".

    Anything unrecognised is returned untouched rather than guessed at.
    """
    m = _PERIOD.fullmatch(key.strip())
    if not m:
        return key
    year, part = m.groups()
    if not part:
        return year
    if part in MONTHS:
        return f"{year}-{MONTHS[part]}"
    if re.fullmatch(r"[1-4]Q", part):
        return f"{year}-Q{part[0]}"
    if re.fullmatch(r"[12]H", part):
        return f"{year}-S{part[0]}"
    return key


def _within(p: str, start: str | None, end: str | None) -> bool:
    """Compared on a prefix, so end="2024" keeps every month of 2024 rather
    than dropping them all for sorting after the bare year."""
    return ((not start or p[:len(start)] >= start)
            and (not end or p[:len(end)] <= end))


def _get(path: str, params: dict | None = None) -> dict:
    r = cache.session().get(f"{BASE}/{path}", params=params or {},
                            timeout=cache.TIMEOUT)
    r.raise_for_status()
    return r.json()["Data"]


@lru_cache(maxsize=64)
def _search(keyword: str) -> tuple:
    return tuple(_get("resourceid", {"keyword": keyword,
                                     "searchOption": "all"}).get("records", []))


@lru_cache(maxsize=64)
def _table(flow: str, series: str = "") -> dict:
    params = {"seriesNoORrowNo": series} if series else {}
    return _get(f"tabledata/{flow}", params)


def dataflows(search: str | None, limit: int) -> dict:
    """The catalogue has no browse-all endpoint, so a keyword is required."""
    if not search:
        return {"error": "SINGSTAT has no catalogue listing; pass a search term, "
                         "e.g. 'consumer price index' or 'gross domestic product'"}
    hits = _search(search)
    return {"total": len(hits),
            "shown": [{"id": h["id"], "name": h["title"], "topic": h.get("topic")}
                      for h in hits[:limit]]}


def describe(flow: str) -> dict:
    d = _table(flow)
    rows = d.get("row", [])
    return {
        "provider": "SINGSTAT", "flow": flow, "name": d.get("title"),
        "frequency": d.get("frequency"), "source": d.get("datasource"),
        "updated": d.get("dataLastUpdated"),
        "dimensions": [{
            "id": DIMENSION,
            "codes": len(rows),
            "sample": [{"id": r["seriesNo"], "name": r["rowText"]}
                       for r in rows[:8]],
        }],
        "note": "Periods are returned in SDMX form; the API's own notation "
                "(1961 Jan, 1961 1Q) is not used.",
    }


def codes(flow: str, dimension: str, query: str, limit: int) -> dict:
    if dimension.upper() != DIMENSION:
        return {"error": f"SINGSTAT tables have one dimension, {DIMENSION}"}
    q = query.lower()
    hits = [{"id": r["seriesNo"], "name": r["rowText"], "unit": r.get("uoM")}
            for r in _table(flow).get("row", [])
            if not q or q in r["rowText"].lower()]
    return {"total": len(hits), "shown": hits[:limit]}


def frame(flow: str, key: dict, start: str | None, end: str | None):
    series = str(key.get(DIMENSION, "") or "")
    rows = _table(flow, series).get("row", [])
    records = [(r["seriesNo"], r.get("uoM") or "", period(c["key"]), c["value"])
               for r in rows for c in r["columns"]]
    df = pd.DataFrame(records, columns=[DIMENSION, UNIT, "TIME_PERIOD", "value"])
    df = df[[_within(p, start, end) for p in df["TIME_PERIOD"]]]
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    return df
