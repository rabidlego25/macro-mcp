"""GLEIF LEI lookup: the only free cross-jurisdiction company key.

Tickers collide across venues and CIK is US-only, so entities resolve here first.
"""

import unicodedata

import requests

from . import cache

BASE = "https://api.gleif.org/api/v1"


def _get(path: str, **params):
    r = cache.session().get(f"{BASE}/{path}", params=params, timeout=cache.TIMEOUT,
                            headers={"Accept": "application/vnd.api+json"})
    r.raise_for_status()
    return r.json()


def _norm(text: str) -> str:
    """Lowercased, whitespace-collapsed, and stripped of accents.

    Without the last part "Nestle" scores nothing against "NESTLÉ S.A." and the
    company ranks below its own subsidiaries. GLEIF matches accents either way;
    the ranking here has to as well.
    """
    folded = unicodedata.normalize("NFKD", str(text or "").lower())
    return " ".join("".join(c for c in folded
                            if not unicodedata.combining(c)).split())


# A branch and a fund are named after the parent, so a query that matches the
# parent matches them too. When the names tie, the operating company is what
# was meant: "Banco Santander" returns the Dutch and French branches, both
# legally "Banco Santander S.A.", alongside the Spanish company they belong to.
_CATEGORY = {"BRANCH": 1, "FUND": 2}


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
    return (best,
            _CATEGORY.get(hit.get("category"), 0),
            0 if hit.get("status") == "ACTIVE" else 1,
            len(hit["name"]))


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
        "category": e.get("category"),
        "bic": a.get("bic") or [],
    }


def search(name: str, country: str | None = None, limit: int = 10) -> dict:
    """Search by name across scripts. Uses fulltext rather than legal-name match:
    many entities are registered in their native script, so Toyota's legal name is
    トヨタ自動車株式会社 and a Latin-script legal-name filter returns nothing.

    Matching is broad, so check country and status on every hit before using it.
    "category" says whether a hit is the operating company, a branch of one, or
    a fund named after it.

    Searched over names rather than fulltext. Fulltext also matches addresses,
    and Santander is a Spanish city as well as a bank: it answered "Banco
    Santander" with 41 records led by an unrelated local company, and did not
    return the bank itself in the first twenty-five at all. `entity.names`
    covers the legal name and the other names GLEIF holds, which is what the
    Japanese-script case needs too, so it finds トヨタ自動車株式会社 from
    "Toyota Motor Corporation" without matching everything near a Toyota
    factory. Hits are then ranked here, since GLEIF's order is not relevance.
    """
    # Ask for more than will be returned, in one request, because ranking a
    # page cannot rescue an entity that was never on it.
    p = {"filter[entity.names]": name, "page[size]": min(max(limit * 5, 25), 200)}
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
