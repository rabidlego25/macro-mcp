"""Point-in-time access: what a statistic said when it was published.

Almost every provider here overwrites its history in place, so a series read
today is as-revised, not as-known. Backtests built on it quietly assume the
analyst had numbers nobody had at the time.

IMF is the exception: it republishes whole dataflows as monthly vintages named
FAMILY_YYYY_MON_VINTAGE beside the current FAMILY. Japan's 2024 nominal GDP
reads 634,226.0bn in the April 2026 vintage and 634,751.3bn in the current one,
a revision nothing that reads only the current flow can see.

Coverage varies between vintages as well as values — one 2026 vintage of the
national accounts carries 18,068 observations and another 204 — so a key absent
from a vintage is reported as such rather than treated as an error.
"""

import re

from . import sdmx_api as api

# IMF's naming, e.g. ANEA_2026_JAN_VINTAGE.
STAMP = re.compile(r"^(.+)_(\d{4})_([A-Z]{3})_VINTAGE$")
MONTHS = {m: i for i, m in enumerate(
    "JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split(), 1)}

# Each vintage is a separate request against a slow service.
DEFAULT_LIMIT = 5


def family(flow: str) -> str:
    """The dataflow a vintage belongs to. Its own id, if it is not one."""
    m = STAMP.fullmatch(flow)
    return m.group(1) if m else flow


def released(flow: str) -> tuple[int, int]:
    """Publication date, for ordering. The current flow sorts newest."""
    m = STAMP.fullmatch(flow)
    return (int(m.group(2)), MONTHS.get(m.group(3), 0)) if m else (9999, 99)


def available(provider: str, flow: str) -> dict:
    """Every vintage of a flow, oldest first, with the current flow last."""
    base = family(flow)
    found = api.dataflows(provider, base, 500)
    if "error" in found:
        return found
    ids = sorted({s["id"] for s in found["shown"] if family(s["id"]) == base},
                 key=released)
    if not [i for i in ids if STAMP.fullmatch(i)]:
        return {"flow": base, "vintages": [],
                "note": f"{provider} publishes no vintages of {base}; its history "
                        "reads as-revised rather than as-known"}
    return {"flow": base, "vintages": ids, "current": base if base in ids else None}


def compare(provider: str, flow: str, key: dict, start: str | None = None,
            end: str | None = None, limit: int = DEFAULT_LIMIT) -> dict:
    """The same key read from several vintages, and what changed between them."""
    found = available(provider, flow)
    if not found.get("vintages"):
        return found
    ids = found["vintages"][-limit:]

    series, missing = {}, []
    for fid in ids:
        out = api.fetch(provider, fid, key, start, end)
        obs = {p: v for s in out.get("series", []) for p, v in s["observations"]}
        if obs:
            series[fid] = obs
        else:
            missing.append(fid)

    read = [i for i in ids if i in series]
    revisions = []
    for older, newer in zip(read, read[1:]):
        for period in sorted(series[older].keys() & series[newer].keys()):
            was, now = series[older][period], series[newer][period]
            if was != now:
                revisions.append({"period": period, "was": was, "now": now,
                                  "between": [older, newer],
                                  "change_pct": round((now - was) / was * 100, 4) if was else None})

    out = {"flow": found["flow"], "key": key, "vintages": read,
           "columns": ["period", "value"],
           "series": [{"vintage": i, "observations": [[p, v] for p, v in sorted(series[i].items())]}
                      for i in read],
           "revisions": revisions}
    if missing:
        out["no_data"] = missing
    if not revisions and len(read) > 1:
        out["note"] = "identical across these vintages; the series was not revised"
    return out
