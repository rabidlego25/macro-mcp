"""SDMX access across the free statistical providers that share ISO 17369."""

from functools import lru_cache

import sdmx
from sdmx.source import sources as _sources

from . import bundesbank

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
    "international": ["BIS", "IMF_DATA3", "OECD", "WB_WDI", "WB", "ILO", "UNSD", "UNICEF"],
    "europe": ["ECB", "ESTAT3", "ESTAT", "ESTAT_COMEXT", "COMP", "EMPL", "GROW"],
    "national_eu": ["BBK", "INSEE", "ISTAT", "NBB", "NB", "LSD"],
    "americas": ["StatCan", "INEGI", "AR1", "UY110"],
    "asia_pacific": ["ABS", "SPC"],
}

# Verified against the live services on 2026-08-10. Surfaced rather than hidden.
QUIRKS = {
    "BBK": "non-standard paths and separate codelists; data needs a pinned key",
    "COMP": "unreachable: webgate path 404s",
    "UY110": "self-signed TLS certificate, so requests fail verification",
    "ISTAT": "intermittent 500s; retry before concluding it is down",
    "INEGI": "only republished OECD/SDG flows, not Mexico's own statistics",
    "OECD": "slow (~11s) and flow ids carry an agency prefix, e.g. ESTAT:NAME(1.4)",
    "INSEE": "invalid concept identity references",
    "ESTAT": "large queries return a footer with a ZIP URL instead of data",
    "StatCan": "only /data/ over REST; structures are static files",
    "AR1": "static XML files, data messages only",
    "UNICEF": "structure-specific data; DSD must be fetched separately",
}


@lru_cache(maxsize=32)
def _client(provider: str) -> sdmx.Client:
    return sdmx.Client(provider)


@lru_cache(maxsize=32)
def _flows(provider: str):
    if provider == "BBK":
        return bundesbank.flows()
    kw = {"agency_id": AGENCY[provider]} if provider in AGENCY else {}
    return _client(provider).dataflow(**kw).dataflow


@lru_cache(maxsize=64)
def _dsd(provider: str, flow: str):
    if provider == "BBK":
        return bundesbank.dsd(flow)
    kw = {"agency_id": AGENCY[provider]} if provider in AGENCY else {}
    return _client(provider).dataflow(flow, **kw).structure[0]


def _codes(dim, provider: str | None = None):
    rep = getattr(dim, "local_representation", None)
    cl = getattr(rep, "enumerated", None) if rep else None
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


def _supports(provider: str, resource: str) -> bool:
    return any(str(k).endswith(f".{resource}") and v
               for k, v in _client(provider).source.supports.items())


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
    return {"provider": provider, "flow": flow, "dimensions": dims,
            "note": "TIME_PERIOD is not part of the key; use start/end instead."}


def search_codes(provider: str, flow: str, dimension: str, query: str = "", limit: int = 30) -> dict:
    """Resolve a dimension value. Also the correct way to map a country onto a
    provider's REF_AREA codelist, which is provider-specific."""
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


def _pack(df, limit: int) -> dict:
    """Hoist the invariant part of the key and nest the rest as series.

    A row-per-observation frame repeats the whole key on every row, which on a
    16-dimension flow costs ~450 redundant bytes an observation. Empty
    observations are dropped rather than serialised: NaN is not valid JSON, and
    a daily series is roughly a third weekends.
    """
    empty = int(df["value"].isna().sum())
    df = df[df["value"].notna()].sort_values("TIME_PERIOD", kind="stable")
    total = len(df)
    truncated = total > limit
    if truncated:
        df = df.tail(limit)  # most recent; `range` states what came back

    dims = [c for c in df.columns if c not in ("TIME_PERIOD", "value")]
    fixed = {d: str(df[d].iloc[0]) for d in dims if df[d].nunique() == 1} if total else {}
    vary = [d for d in dims if d not in fixed]

    def obs(g):
        return [[str(p), float(v)] for p, v in zip(g["TIME_PERIOD"], g["value"])]

    if not total:
        series = []
    elif vary:
        series = [{"key": dict(zip(vary, (str(x) for x in (k if isinstance(k, tuple) else (k,))))),
                   "observations": obs(g)} for k, g in df.groupby(vary, sort=False)]
    else:
        series = [{"key": {}, "observations": obs(df)}]

    out = {"key": fixed, "columns": ["period", "value"], "series": series, "total": total}
    if total:
        out["range"] = [str(df["TIME_PERIOD"].iloc[0]), str(df["TIME_PERIOD"].iloc[-1])]
    if truncated:
        out["truncated"] = f"most recent {limit} of {total}; narrow start/end for the rest"
    if empty:
        out["empty"] = empty
    return out


def fetch(provider: str, flow: str, key: dict, start: str | None = None,
          end: str | None = None, limit: int = 500) -> dict:
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
    df = sdmx.to_pandas(msg).reset_index()
    df.columns = [*df.columns[:-1], "value"]
    return _pack(df, limit)
