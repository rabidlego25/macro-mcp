"""SDMX access across the free statistical providers that share ISO 17369."""

import re
from functools import lru_cache

import sdmx
from sdmx.source import sources as _sources

from . import bundesbank, cache, hkma, singstat

# Providers that do not speak SDMX at all. Each implements the same four calls
# and returns the same response shapes, so they reach the agent through the
# same tools rather than growing a parallel set.
NATIVE = {"SINGSTAT": singstat, "HKMA": hkma}

# sdmx1 ships hardcoded endpoints that drift as institutions move. These are
# verified against the live services rather than the library's registry.
URL_FIXES = {
    "ABS": "https://data.api.abs.gov.au/rest",  # api.data.abs.gov.au stopped resolving
    "LSD": "https://osp-rs.stat.gov.lt/ords/ipospp/ospp/rest_xml",  # moved to APEX
}
for _p, _u in URL_FIXES.items():
    _sources[_p].url = _u

# Providers whose flows are filed under agencies other than the source id.
AGENCY = {"INEGI": "all"}

# Provider ids as used by sdmx1. All keyless except UNESCO (free registration).
GROUPS = {
    "international": ["BIS", "IMF_DATA", "OECD", "WB_WDI", "WB", "ILO", "UNSD", "UNICEF"],
    "europe": ["ECB", "ESTAT3", "ESTAT", "ESTAT_COMEXT", "COMP", "EMPL", "GROW"],
    "national_eu": ["BBK", "INSEE", "ISTAT", "NBB", "NB", "LSD"],
    "americas": ["StatCan", "INEGI", "AR1", "UY110"],
    "asia_pacific": ["ABS", "SPC", "SINGSTAT", "HKMA"],
}

# Verified against the live services on 2026-08-10. Surfaced rather than hidden.
QUIRKS = {
    "BBK": "non-standard paths and separate codelists; data needs a pinned key",
    "COMP": "unreachable: webgate path 404s",
    "UY110": "self-signed TLS certificate, so requests fail verification",
    "ISTAT": "intermittent 500s; retry before concluding it is down",
    "INEGI": "only republished OECD/SDG flows, not Mexico's own statistics",
    "OECD": "flow ids carry an agency prefix, e.g. ESTAT:SEEA_AEA_A(1.4); pass them back whole",
    "ESTAT3": "reachable but returns an empty dataflow list; use ESTAT",
    "INSEE": "invalid concept identity references",
    "ESTAT": "large queries return a footer with a ZIP URL instead of data",
    "StatCan": "only /data/ over REST; structures are static files",
    "NBB": "no dataflow endpoint; the flow id must be known in advance",
    "AR1": "static XML files, data messages only",
    "UNICEF": "structure-specific data; DSD must be fetched separately",
    "SINGSTAT": "not SDMX; no catalogue listing, so find_dataflows needs a search term",
    "HKMA": "not SDMX; one wide table per dataset, so each column is a SERIES code",
}


# What each provider actually serves, probed end to end through this module
# rather than read from sdmx1's `source.supports`. That table is wrong in both
# directions: it advertises metadata for BBK, whose every standard path 404s,
# and it is static, so it cannot know that the adapter here makes BBK work.
# Probed 2026-08-10 (all 29, including the non-SDMX adapters); regenerate with `MACRO_MCP_NO_CACHE=1 uv run python -m scripts.probe`.
SUPPORTS = {
    "BIS": ("dataflow", "datastructure"),
    "IMF_DATA": ("dataflow", "datastructure"),
    "OECD": ("dataflow", "datastructure"),
    "WB_WDI": (),
    "WB": ("dataflow", "datastructure"),
    "ILO": ("dataflow", "datastructure"),
    "UNSD": ("dataflow", "datastructure"),
    "UNICEF": ("dataflow", "datastructure"),
    "ECB": ("dataflow", "datastructure"),
    "ESTAT3": (),
    "ESTAT": ("dataflow", "datastructure"),
    "ESTAT_COMEXT": ("dataflow", "datastructure"),
    "COMP": (),
    "EMPL": ("dataflow", "datastructure"),
    "GROW": ("dataflow", "datastructure"),
    "BBK": ("dataflow", "datastructure"),
    "INSEE": ("dataflow", "datastructure"),
    "ISTAT": ("dataflow", "datastructure"),
    "NBB": (),
    "NB": ("dataflow", "datastructure"),
    "LSD": ("dataflow", "datastructure"),
    "StatCan": (),
    "INEGI": ("dataflow", "datastructure"),
    "AR1": (),
    "UY110": (),
    "ABS": ("dataflow", "datastructure"),
    "SPC": ("dataflow", "datastructure"),
    "SINGSTAT": ("dataflow", "datastructure"),
    "HKMA": ("dataflow", "datastructure"),
}

# Providers absent from SUPPORTS are assumed capable, so adding one to GROUPS
# does not require a probe first.
DEFAULT_SUPPORT = ("dataflow", "datastructure")


@lru_cache(maxsize=32)
def _client(provider: str) -> sdmx.Client:
    return sdmx.Client(provider, session=cache.session())


@lru_cache(maxsize=32)
def _flows(provider: str):
    if provider == "BBK":
        return bundesbank.flows()
    kw = {"agency_id": AGENCY[provider]} if provider in AGENCY else {}
    return _client(provider).dataflow(**kw).dataflow


# Flow ids may carry SDMX's AGENCY:ID(VERSION) notation — OECD's all do. sdmx1
# puts the whole string in the id slot and builds a URL the service rejects, so
# the parts are split out and passed separately.
_FLOW_KEY = re.compile(r"(?:([^:]+):)?([^()]+)(?:\((.+)\))?")


@lru_cache(maxsize=64)
def _dsd(provider: str, flow: str):
    if provider == "BBK":
        return bundesbank.dsd(flow)
    agency, flow_id, version = _FLOW_KEY.fullmatch(flow).groups()
    kw = {"agency_id": agency or AGENCY.get(provider), "version": version}
    return _client(provider).dataflow(
        flow_id, **{k: v for k, v in kw.items() if v}).structure[0]


def _codes(dim, provider: str | None = None):
    rep = getattr(dim, "local_representation", None)
    cl = getattr(rep, "enumerated", None) if rep else None
    if cl is None:
        # SDMX lets a dimension take its codelist from the concept it identifies
        # rather than restate one. IMF's dimensions declare no local
        # representation at all, so this is the only place their codes live.
        core = getattr(getattr(dim, "concept_identity", None), "core_representation", None)
        cl = getattr(core, "enumerated", None) if core else None
    # BBK inlines an empty codelist and publishes the real one separately.
    if not cl and provider == "BBK":
        return bundesbank.codelist(dim.id)
    return cl


def _names(obj) -> dict:
    """SDMX names are multilingual and providers ship English alongside the native
    language in one response, so nothing needs translating.

    Empty localizations are dropped; BBK publishes a null English name on some
    flows, which would otherwise mask the German one.
    """
    name = getattr(obj, "name", None)
    loc = getattr(name, "localizations", None)
    if loc:
        return {k: v for k, v in loc.items() if v}
    return {"": str(name)} if name else {}


def _label(names: dict) -> str:
    return names.get("en") or next(iter(names.values()), "")


def _matches(q: str, ident: str, names: dict) -> bool:
    """Match across every localization, so an English query finds an Italian
    dataflow and vice versa."""
    return q in ident.lower() or any(q in s.lower() for s in names.values())


# Attributes that say what a number is measured in. A bare 634751300000000.0 is
# not an answer to "what was Japan's GDP" — it is 634.75tn yen or 634.75bn,
# depending on a multiplier the provider ships and sdmx1 discards by default.
#
# Matched by pattern rather than listed, because the name differs per provider:
# BIS and ILO write UNIT_MEASURE/UNIT_MULT, ECB writes UNIT and
# UNIT_INDEX_BASE, BBK prefixes its own with BBK_, and IMF publishes neither
# but does populate SCALE. Everything else a provider attaches is prose or
# process metadata — BIS alone ships 2.5KB of compilation notes per series —
# and is dropped, since this response format exists to be small.
_UNIT = re.compile(r"(^|_)(UNIT|SCALE)(_|$)")


def _is_unit(name: str) -> bool:
    return bool(_UNIT.search(name))


@lru_cache(maxsize=64)
def _unit_labels(provider: str, flow: str) -> dict:
    """Code to English label, per unit attribute.

    The values arrive as codes — BIS sends UNIT_MEASURE="368" — which are no
    more use to an agent than the bare number was. They resolve through the
    same codelist machinery the dimensions use, against a DSD describe_flow has
    usually already cached. A provider that serves no structure metadata leaves
    the raw code, which beats dropping it.
    """
    try:
        dsd = _dsd(provider, flow)
    except Exception:
        return {}
    out = {}
    for a in getattr(getattr(dsd, "attributes", None), "components", []):
        if not _is_unit(a.id):
            continue
        cl = _codes(a, provider)
        if cl is not None:
            out[a.id] = {c.id: _label(_names(c)) for c in cl}
    return out


def _supports(provider: str, resource: str) -> bool:
    return resource in SUPPORTS.get(provider, DEFAULT_SUPPORT)


def _entry(p: str) -> dict:
    e = {"id": p, "metadata": _supports(p, "dataflow")}
    if p in QUIRKS:
        e["quirk"] = QUIRKS[p]
    if not e["metadata"]:
        e["note"] = "data only; dataflow id must be known in advance"
    return e


def providers() -> dict:
    return {g: [_entry(p) for p in ps] for g, ps in GROUPS.items()}


def dataflows(provider: str, search: str | None = None, limit: int = 40) -> dict:
    if provider in NATIVE:
        return NATIVE[provider].dataflows(search, limit)
    if not _supports(provider, "dataflow"):
        return {"error": f"{provider} serves data but not dataflow metadata; "
                         "supply a known flow id to fetch_data directly"}
    flows = _flows(provider)
    items = [(k, _names(v)) for k, v in flows.items()]
    if search:
        q = search.lower()
        items = [(k, n) for k, n in items if _matches(q, k, n)]
    return {"total": len(items),
            "shown": [{"id": k, "name": _label(n)} for k, n in items[:limit]]}


def describe_flow(provider: str, flow: str, code_sample: int = 8) -> dict:
    """Dimensions with code counts and a sample. Full lists come from search_codes."""
    if provider in NATIVE:
        return NATIVE[provider].describe(flow)
    if not _supports(provider, "datastructure"):
        return {"error": f"{provider} does not publish structure metadata"}
    dims = []
    for d in _dsd(provider, flow).dimensions.components:
        cl = _codes(d, provider)
        n = len(cl) if cl is not None else 0
        names = [_names(c) for c in cl] if n else []
        dim = {
            "id": d.id,
            "codes": n,
            "sample": [{"id": c.id, "name": _label(nm)}
                       for c, nm in zip(list(cl)[:code_sample], names)] if n else [],
        }
        # Tell the agent when labels are not in English, so it queries natively
        # instead of silently matching nothing.
        if n and not all(nm.get("en") for nm in names):
            langs = sorted({k for nm in names for k in nm if k})
            dim["english_labels"] = f"{sum(1 for nm in names if nm.get('en'))}/{n}"
            dim["languages"] = langs or ["unlabelled"]
        dims.append(dim)
    if not dims:
        # A structure with no dimensions cannot be queried, so returning one as
        # if it were an answer just moves the failure to fetch_data. IMF used to
        # land here, via a DSD that parsed cleanly and was empty.
        return {"error": f"{provider} returned a structure for {flow} with no "
                         "dimensions; the flow may be unqueryable"}
    return {"provider": provider, "flow": flow, "dimensions": dims,
            "note": "TIME_PERIOD is not part of the key; use start/end instead."}


def search_codes(provider: str, flow: str, dimension: str, query: str = "", limit: int = 30) -> dict:
    """Resolve a dimension value. Also the correct way to map a country onto a
    provider's REF_AREA codelist, which is provider-specific."""
    if provider in NATIVE:
        return NATIVE[provider].codes(flow, dimension, query, limit)
    for d in _dsd(provider, flow).dimensions.components:
        if d.id.upper() != dimension.upper():
            continue
        cl = _codes(d, provider)
        if cl is None:
            return {"error": f"{dimension} has no codelist"}
        q = query.lower()
        hits = [{"id": c.id, "name": _label(n)} for c in cl
                for n in [_names(c)] if not q or _matches(q, c.id, n)]
        return {"total": len(hits), "shown": hits[:limit]}
    return {"error": f"no dimension {dimension} in {flow}"}


# IMF writes monthly periods as 2024-M01 rather than SDMX's 2024-01. Its
# quarters and years are already standard, so only the month infix is dropped.
# Left unrewritten, an IMF series silently fails to join against every other
# provider on this list.
_MONTH = re.compile(r"^(\d{4})-M(\d{2})$")


def _period(p) -> str:
    return _MONTH.sub(r"\1-\2", str(p))


def _shares(lengths: list[int], limit: int) -> list[int]:
    """Split a budget of observations across series, max-min fair.

    An even split clips a long series even when the whole response would have
    fitted, so a series shorter than its share hands the surplus back to the
    longer ones. Nothing is truncated while the budget still has room.
    """
    shares, rest = [0] * len(lengths), limit
    for taken, i in enumerate(sorted(range(len(lengths)), key=lambda i: lengths[i])):
        shares[i] = min(lengths[i], rest // (len(lengths) - taken))
        rest -= shares[i]
    return shares


def _split(d: dict, units) -> tuple[dict, dict]:
    """Dimensions and units travel together through grouping and part here.

    A unit is not part of the key. Returned inside it, an agent would echo it
    back to fetch_data as a dimension and get an error from the provider.
    """
    return ({k: v for k, v in d.items() if k not in units},
            {k: v for k, v in d.items() if k in units})


def _identify(d: dict, units) -> dict:
    key, unit = _split(d, units)
    return {"key": key, "units": unit} if unit else {"key": key}


def _pack(df, limit: int, units: tuple = ()) -> dict:
    """Hoist the invariant part of the key and nest the rest as series.

    A row-per-observation frame repeats the whole key on every row, which on a
    16-dimension flow costs ~450 redundant bytes an observation. Empty
    observations are dropped rather than serialised: NaN is not valid JSON, and
    a daily series is roughly a third weekends.
    """
    empty = int(df["value"].isna().sum())
    df = df[df["value"].notna()].sort_values("TIME_PERIOD", kind="stable")
    total = len(df)

    # Hoisting is decided before truncation. Deciding it afterwards let a series
    # that truncation had deleted entirely make the survivor's key look
    # invariant, so a two-series request came back reading as though only one
    # series had ever been asked for.
    # Units are grouped on exactly as dimensions are, so a response mixing
    # percent with index says so instead of interleaving the two silently.
    dims = [c for c in df.columns if c not in ("TIME_PERIOD", "value")]
    fixed = {d: str(df[d].iloc[0]) for d in dims if df[d].nunique() == 1} if total else {}
    vary = [d for d in dims if d not in fixed]

    def skey(k):
        return dict(zip(vary, (str(x) for x in (k if isinstance(k, tuple) else (k,)))))

    if not total:
        groups = []
    elif vary:
        groups = [(skey(k), g) for k, g in df.groupby(vary, sort=False)]
    else:
        groups = [({}, df)]

    # The budget is shared out per series rather than spent oldest-first across
    # the whole response, which dropped entire series off the old end and then
    # reported only that some total had been exceeded.
    kept, dropped = groups[:limit], [k for k, _ in groups[limit:]]
    shares = _shares([len(g) for _, g in kept], limit)
    tails = [(k, g.tail(n)) for (k, g), n in zip(kept, shares)]
    shown = sum(len(g) for _, g in tails)

    series = [{**_identify(k, units),
               "observations": [[_period(p), float(v)]
                                for p, v in zip(g["TIME_PERIOD"], g["value"])]}
              for k, g in tails]

    hoisted, hoisted_units = _split(fixed, units)
    out = {"key": hoisted, "columns": ["period", "value"], "series": series,
           "total": total}
    if hoisted_units:
        out["units"] = hoisted_units
    if shown:
        periods = [str(p) for _, g in tails for p in g["TIME_PERIOD"]]
        out["range"] = [_period(min(periods)), _period(max(periods))]
    if shown < total:
        out["truncated"] = (f"most recent {shown} of {total}" if len(groups) == 1 else
                            f"most recent {shown} of {total}, at most "
                            f"{max(shares, default=0)} per series"
                            ) + "; narrow start/end for the rest"
    if dropped:
        out["dropped_series"] = {"count": len(dropped),
                                 "keys": [_split(k, units)[0] for k in dropped[:10]]}
    if empty:
        out["empty"] = empty
    return out


def _attribute_ids(msg) -> set:
    """Attribute ids carried by a data message, at any of its three levels.

    Read off the message rather than the DSD, so telling a unit from a
    dimension never costs a structure request. Only turning its code into a
    label does.
    """
    ids = set()
    for ds in getattr(msg, "data", []) or []:
        ids |= set(getattr(ds, "attrib", {}) or {})
        for sk, obs in (getattr(ds, "series", {}) or {}).items():
            ids |= set(getattr(sk, "attrib", {}) or {})
            for o in list(obs)[:1]:
                ids |= set(getattr(o, "attached_attribute", {}) or {})
        for o in list(getattr(ds, "obs", []) or [])[:1]:
            ids |= set(getattr(o, "attached_attribute", {}) or {})
    return ids


def _dimension_ids(msg) -> set:
    """Dimension ids carried by a data message, from the series keys."""
    ids = set()
    for ds in getattr(msg, "data", []) or []:
        for sk in (getattr(ds, "series", {}) or {}):
            ids |= set(getattr(sk, "values", {}) or {})
        for o in list(getattr(ds, "obs", []) or [])[:1]:
            ids |= set(getattr(getattr(o, "key", None), "values", {}) or {})
    return ids


def _text(v) -> str:
    t = "" if v is None else str(v).strip()
    return "" if t in ("nan", "None", "NaN") else t


def _frame(msg, provider: str, flow: str):
    """Observations, plus whatever says what they are measured in.

    Returns the frame and the names of its unit columns. Attributes are asked
    for only when the message carries a unit, because asking has two costs:
    every other attribute arrives too — BIS ships 2.5KB of compilation notes
    per series, against a response format whose whole point is 6KB — and
    `value` stops being the last column, which the rename below assumes.
    """
    attrs = _attribute_ids(msg)
    units = sorted(a for a in attrs if _is_unit(a))
    if not units:
        df = sdmx.to_pandas(msg).reset_index()
        df.columns = [*df.columns[:-1], "value"]
        return df, ()

    df = sdmx.to_pandas(msg, attributes="dso").reset_index()
    if "value" not in df.columns:
        df.columns = [*df.columns[:-1], "value"]

    labels = _unit_labels(provider, flow)
    kept = []
    for u in units:
        if u not in df.columns:
            continue
        raw = [_text(v) for v in df[u]]
        # IMF declares a UNIT attribute on its DSD and never populates it. A
        # column of empty strings would hoist into the response as a fact.
        if not any(raw):
            continue
        codes = labels.get(u, {})
        df[u] = [codes.get(v, v) for v in raw]
        kept.append(u)

    # Allowlist rather than denylist. to_pandas emits a column for every
    # attribute the DSD declares, including ones this message never carried, so
    # excluding what the message did carry left ECB with fourteen empty prose
    # columns — which _pack then hoisted into the key as though they were facts.
    dims = _dimension_ids(msg)
    keep = [c for c in df.columns
            if c in ("TIME_PERIOD", "value") or c in kept
            or (c in dims if dims else c not in attrs)]
    return df[keep], tuple(kept)


def fetch(provider: str, flow: str, key: dict, start: str | None = None,
          end: str | None = None, limit: int = 500) -> dict:
    if provider in NATIVE:
        adapter = NATIVE[provider]
        return _pack(adapter.frame(flow, key, start, end), limit,
                     getattr(adapter, "UNITS", ()))
    params = {}
    if start:
        params["startPeriod"] = start
    if end:
        params["endPeriod"] = end
    if provider == "BBK":
        msg = bundesbank.data(flow, key, params)
    else:
        try:
            msg = _client(provider).data(flow, key=key, params=params)
        except sdmx.exceptions.XMLParseError:
            # Some providers (BIS) serve structure-specific data referencing a DSD
            # sdmx1 cannot resolve. Generic SDMX-ML parses cleanly.
            msg = _client(provider).data(
                flow, key=key, params=params,
                headers={"Accept": "application/vnd.sdmx.genericdata+xml;version=2.1"})
    df, units = _frame(msg, provider, flow)
    return _pack(df, limit, units)
