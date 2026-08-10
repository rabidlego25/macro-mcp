"""GLEIF LEI lookup: the only free cross-jurisdiction company key.

Tickers collide across venues and CIK is US-only, so entities resolve here first.
"""

import requests

from . import cache

BASE = "https://api.gleif.org/api/v1"


def _get(path: str, **params):
    r = cache.session().get(f"{BASE}/{path}", params=params, timeout=cache.TIMEOUT,
                            headers={"Accept": "application/vnd.api+json"})
    r.raise_for_status()
    return r.json()


def _summary(rec: dict) -> dict:
    a = rec["attributes"]
    e = a["entity"]
    others = [n["name"] for n in (e.get("otherNames") or [])]
    others += [n["name"] for n in (e.get("transliteratedOtherNames") or [])]
    return {
        "lei": rec["id"],
        "name": e["legalName"]["name"],
        "other_names": others[:4],
        "country": e["legalAddress"]["country"],
        "jurisdiction": e.get("jurisdiction"),
        "status": e["status"],
        "bic": a.get("bic") or [],
    }


def search(name: str, country: str | None = None, limit: int = 10) -> dict:
    """Search by name across scripts. Uses fulltext rather than legal-name match:
    many entities are registered in their native script, so Toyota's legal name is
    トヨタ自動車株式会社 and a Latin-script legal-name filter returns nothing.

    Matching is broad, so check country and status on every hit before using it.
    """
    p = {"filter[fulltext]": name, "page[size]": limit}
    if country:
        p["filter[entity.legalAddress.country]"] = country.upper()
    d = _get("lei-records", **p)
    return {"total": d.get("meta", {}).get("pagination", {}).get("total"),
            "hits": [_summary(r) for r in d["data"]]}


def get(lei: str) -> dict:
    return _summary(_get(f"lei-records/{lei}")["data"])


def ownership(lei: str) -> dict:
    """Direct and ultimate parents, plus children. Needed for real exposure
    questions, which never stop at the listed entity."""
    out = {"lei": lei}
    for rel, path in [("direct_parent", "direct-parent"),
                      ("ultimate_parent", "ultimate-parent")]:
        try:
            out[rel] = _summary(_get(f"lei-records/{lei}/{path}")["data"])
        except requests.HTTPError:
            out[rel] = None
    try:
        kids = _get(f"lei-records/{lei}/direct-children", **{"page[size]": 50})
        out["direct_children"] = [_summary(r) for r in kids["data"]]
    except requests.HTTPError:
        out["direct_children"] = []
    return out
