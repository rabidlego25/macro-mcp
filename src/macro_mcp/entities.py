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


def _norm(text: str) -> str:
    return " ".join(str(text or "").lower().split())


def _total(payload: dict):
    return payload.get("meta", {}).get("pagination", {}).get("total")


def _score(query: str, hit: dict) -> tuple:
    """How well a hit answers the name that was asked for.

    GLEIF's fulltext order is not relevance and it is what an agent reads first.
    "Banco Santander" returns 41 hits led by an unrelated company that matches
    because Santander is also a Spanish city, and filtered to ES the bank is
    the last of five, behind a mutual society and a foundation. Nothing in a
    record separates them except the names, so the ordering has to come from
    there: an exact legal name first, then one that starts with the query, then
    one that merely contains it, and the shorter name breaks a tie because the
    parent company is rarely the longest name matching it.
    """
    q = _norm(query)
    best = 3
    for name in (hit["name"], *hit["other_names"]):
        n = _norm(name)
        if n == q:
            best = min(best, 0)
        elif n.startswith(q):
            best = min(best, 1)
        elif q in n:
            best = min(best, 2)
    return (best, len(hit["name"]))


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
    Hits are ranked by how closely each name matches, not in GLEIF's own order:
    fulltext also matches addresses, and Santander is a city as well as a bank.
    """
    # Ask for more than will be returned, in one request, because ranking a
    # page cannot rescue an entity that was never on it: "Banco Santander"
    # matches 41 records and the bank is not among the first five.
    p = {"filter[fulltext]": name, "page[size]": min(max(limit * 5, 25), 200)}
    if country:
        p["filter[entity.legalAddress.country]"] = country.upper()
    d = _get("lei-records", **p)
    hits = sorted((_summary(r) for r in d["data"]),
                  key=lambda h: _score(name, h))
    return {"total": _total(d), "hits": hits[:limit]}


def get(lei: str) -> dict:
    return _summary(_get(f"lei-records/{lei}")["data"])


def _absent(exc: requests.HTTPError) -> bool:
    """Whether GLEIF said the relationship does not exist.

    It answers 404 with an error document rather than an empty one, so absence
    arrives as an exception. Every other status is the service failing, and
    reading that as "no parent" turns an outage into a fact about the company —
    which is the shape of wrong answer this whole module exists to avoid.
    """
    return exc.response is not None and exc.response.status_code == 404


def ownership(lei: str) -> dict:
    """Direct and ultimate parents, plus children. Needed for real exposure
    questions, which never stop at the listed entity."""
    out = {"lei": lei}
    for rel, path in [("direct_parent", "direct-parent"),
                      ("ultimate_parent", "ultimate-parent")]:
        try:
            out[rel] = _summary(_get(f"lei-records/{lei}/{path}")["data"])
        except requests.HTTPError as exc:
            if not _absent(exc):
                raise
            out[rel] = None
    try:
        kids = _get(f"lei-records/{lei}/direct-children", **{"page[size]": 50})
        out["direct_children"] = [_summary(r) for r in kids["data"]]
        # A list of 50 that is really the first 50 of 200 reads as the whole
        # ownership tree, and the question this answers is usually whether a
        # subsidiary exists somewhere. Say which of the two it is.
        held = _total(kids)
        out["direct_children_total"] = held
        if held is not None and held > len(out["direct_children"]):
            out["children_truncated"] = (
                f"{len(out['direct_children'])} of {held} shown; GLEIF is asked "
                "for one page and the rest were not fetched")
    except requests.HTTPError as exc:
        if not _absent(exc):
            raise
        out["direct_children"] = []
        out["direct_children_total"] = 0
    return out
