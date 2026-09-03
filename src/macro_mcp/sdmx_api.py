"""SDMX access across the free statistical providers that share ISO 17369."""

import gzip
import json
import pathlib
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


# A query word that begins a word, rather than landing inside one. "employment"
# should prefer "Employment by sex" to "time-related underemployment", but
# "rate" still has to find "rates", so this anchors the start and not the end.
_WORD_START = "(?<![0-9a-z])"


def _rank(q: str, ident: str, names: dict) -> tuple | None:
    """How closely `q` matches, as a sort key, or None if it does not match.

    Matching is across every localization, so an English query finds an Italian
    dataflow and vice versa. Every word of the query has to appear, in any
    order, within one name or the id. A query is typed as a phrase and the
    names are not phrased that way: matching the whole phrase as one substring,
    "national accounts" found one IMF flow and hid ANEA, whose name is
    "National Economic Accounts (NEA), Annual Data". Requiring the words rather
    than the order finds seventeen.

    Which was the smaller half of the problem. Asked for "unemployment", ILO
    returns 108 flows and the headline rate was the 66th of them, behind
    sixty-five breakdowns of itself. A hundred and eight names is not a
    narrower answer than the catalogue, so what matched has to be ordered:

    - an exact match on the id or a name first, which is somebody typing back
      something they already knew;
    - then whether every word begins a word rather than landing inside one;
    - then how far into the field the last of the query's words appears, so a
      name that leads with the subject beats one that mentions it in passing.
      "Unemployment rate by sex and age" beats "SDG indicator 8.5.2:
      Unemployment rate by sex and age";
    - then length, because a dataflow name is a subject followed by the
      breakdowns applied to it, and the headline series is the one carrying
      none of them. "Unemployment rate by sex and age" is the question somebody
      asked; "Unemployment rate by sex, age and marital status" is that series
      cut again.

    The whole key is scored per field and the best field wins, so a flow is
    ranked on the name that matched rather than on the ones that did not.
    """
    words = q.split()
    best = None
    for field in (ident.lower(), *(n.lower() for n in names.values())):
        at, inside = [], False
        for w in words:
            i = field.find(w)
            if i < 0:
                break
            start = re.search(_WORD_START + re.escape(w), field)
            inside = inside or start is None
            at.append(i if start is None else start.start())
        else:
            key = (field != q, inside, max(at, default=0), len(field))
            best = key if best is None else min(best, key)
    return best


def _matches(q: str, ident: str, names: dict) -> bool:
    return _rank(q, ident, names) is not None


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


@lru_cache(maxsize=64)
def _dim_labels(provider: str, flow: str) -> dict:
    """Code to English label, per key dimension.

    The same lookup `_unit_labels` does, against the same DSD, for the
    dimensions rather than the unit attributes. Without it a response says
    COUNTRY: JPN and TYPE_OF_TRANSFORMATION: XDC, and the fact that the number
    is in yen is reachable only by asking search_codes about a dimension the
    caller already filtered on. SingStat is the extreme case: its series are
    keyed 1, 1.0, 1.01, and "1" is All Items.
    """
    try:
        dsd = _dsd(provider, flow)
    except Exception:
        return {}
    out = {}
    for d in getattr(getattr(dsd, "dimensions", None), "components", []):
        if d.id == "TIME_PERIOD":
            continue
        cl = _codes(d, provider)
        if cl is not None:
            out[d.id] = {c.id: _label(_names(c)) for c in cl}
    return out


def _native_labels(adapter, flow: str, dims: list) -> dict:
    """The same map from an adapter that is not SDMX. Its codes() is what
    search_codes already calls, and reads the table this fetch has cached."""
    out = {}
    for d in dims:
        try:
            found = adapter.codes(flow, d, "", 100000)
        except Exception:
            continue
        named = {c["id"]: c["name"] for c in found.get("shown", []) if c.get("name")}
        if named:
            out[d] = named
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


# The shipped cross-provider index: ids and names for every catalogue, built by
# scripts.catalogue. 27,190 flows across 20 providers, 5.3MB of JSON and 0.8MB
# on disk, against a wheel that already pulls 306MB of pandas.
CATALOGUE = pathlib.Path(__file__).parent / "catalogue.json.gz"

ANY = "*"


@lru_cache(maxsize=1)
def _regions() -> dict:
    return {p: g for g, ps in GROUPS.items() for p in ps}


def _region(provider: str) -> str:
    """Which group a provider sits in, carried into a cross-provider answer.

    It is the difference between the two hits a routing question has to choose
    between: ILO covers 190 countries and ISTAT covers Italy, and nothing else
    in the response says so.
    """
    return _regions().get(provider, "")


@lru_cache(maxsize=1)
def _catalogue() -> dict:
    """Provider to [[id, *names], ...], read once per process.

    Hong Kong is folded in from `hkma.FLOWS` rather than built into the file,
    because that table already ships in this package and two copies of it would
    be two things to keep in step. Singapore cannot be indexed at all: it
    publishes no catalogue endpoint, only a search, which is the same reason
    `find_dataflows` demands a search term for it.
    """
    try:
        built = json.loads(gzip.decompress(CATALOGUE.read_bytes()))
    except (OSError, ValueError):
        # A checkout with no index built, or a corrupt one. Every caller
        # degrades to searching one provider at a time, which is where this
        # started, so it is a missing feature rather than a broken one.
        return {}
    index = built["providers"]
    index["HKMA"] = [[slug, slug.replace("-", " ")] for slug in hkma.FLOWS]
    return {"built": built["built"], "providers": index}


def _everywhere(search: str, limit: int) -> dict:
    """Which providers carry a subject, from the index rather than the network.

    An eval asked IMF for unemployment, got `total: 0`, and had no way to learn
    that ILO has 108 flows for it. Answering that live means reading 20
    catalogues, which is 63s of Eurostat and 51s of ISTAT on a cold cache: not
    a tool call. Answering it from the index is one decompression.

    Providers are ordered by their best hit rather than by how many they have,
    because 500 loose matches is a worse answer than one flow named exactly
    what was asked for.
    """
    cat = _catalogue()
    if not cat:
        return {"error": "no cross-provider index in this install; build one "
                         "with `uv run python -m scripts.catalogue`, or search "
                         "one provider at a time"}
    q = search.lower()
    found = []
    for provider, flows in cat["providers"].items():
        # The index keeps distinct names and drops their language tags, since
        # matching reads every localization anyway and the labels were only
        # ever used to pick an English one. Numbering them back gives _rank the
        # shape it wants without inventing tags the file does not carry.
        hits = sorted((r, ident, names[0])
                      for ident, *names in flows
                      if (r := _rank(q, ident, dict(enumerate(names)))) is not None)
        if hits:
            found.append((hits[0][0], provider, hits))
    found.sort()
    return {
        "search": search,
        "total": sum(len(h) for _, _, h in found),
        "providers": [
            {"provider": p, "region": _region(p), "flows": len(hits),
             "sample": [{"id": i, "name": n} for _, i, n in hits[:3]]}
            for _, p, hits in found[:limit]],
        "index_built": cat["built"],
        "note": "a shipped index of provider catalogues, not a live read: it "
                "says where to look, so confirm with find_dataflows against "
                "the provider named. SINGSTAT is absent, having no catalogue "
                "endpoint to index.",
    }


def dataflows(provider: str, search: str | None = None, limit: int = 40) -> dict:
    if provider == ANY:
        if not search:
            return {"error": "searching every provider needs a search term"}
        return _everywhere(search, limit)
    if provider in NATIVE:
        return _or_elsewhere(NATIVE[provider].dataflows(search, limit), search)
    if not _supports(provider, "dataflow"):
        return {"error": f"{provider} serves data but not dataflow metadata; "
                         "supply a known flow id to fetch_data directly"}
    flows = _flows(provider)
    items = [(k, _names(v)) for k, v in flows.items()]
    if search:
        q = search.lower()
        scored = sorted((r, k, n) for k, n in items
                        if (r := _rank(q, k, n)) is not None)
        items = [(k, n) for _, k, n in scored]
    out = {"total": len(items),
           "shown": [{"id": k, "name": _label(n)} for k, n in items[:limit]]}
    # What is cut matters more than how many matched. A total of 108 with 40
    # names under it reads as a catalogue to work through, and the agent that
    # met one read the names and gave up. Say that these are the closest and
    # that the rest are reachable, so the next move is a word rather than a
    # guess.
    if len(items) > limit:
        out["note"] = (
            f"closest {limit} of {len(items)}; add a word to the search to "
            "narrow it, or raise limit to see the rest"
            if search else
            f"first {limit} of {len(items)}, unordered; pass a search term")
    return _or_elsewhere(out, search)


def _or_elsewhere(out: dict, search: str | None) -> dict:
    """Name the providers that do carry it, when this one does not.

    A zero is the least useful thing a search can return, and it was returned
    to an eval that then concluded nothing more. `total: 0` from IMF for
    "unemployment" is true and it is not the answer: ILO has 108. The index is
    already in memory, so saying so costs nothing and no request.
    """
    if not search or out.get("total") or "error" in out:
        return out
    elsewhere = _everywhere(search, limit=4)
    if not elsewhere.get("providers"):
        return out
    out["elsewhere"] = [{"provider": p["provider"], "region": p["region"],
                         "flows": p["flows"]} for p in elsewhere["providers"]]
    out["note"] = (f"no match here; {elsewhere['total']} across other "
                   "providers, listed under elsewhere. Search one of them, or "
                   'pass provider="*" for the whole list.')
    return out


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


def _at_cap(df, cap: int | None, units: tuple) -> bool:
    """Whether the provider-side cap is what ended a series, rather than the
    series ending.

    A series that came back at exactly the cap has older observations the
    request declined to fetch; one that came back shorter is complete, and the
    response can say how long it is. Counted before empties are dropped,
    because the provider counted them too.
    """
    if not cap:
        return False
    dims = [c for c in df.columns
            if c not in ("TIME_PERIOD", "value") and c not in units]
    sizes = df.groupby(dims, sort=False).size() if dims else [len(df)]
    return any(n >= cap for n in sizes)


def _pack(df, limit: int, units: tuple = (), cap: int | None = None,
          asked: dict | None = None, names: dict | None = None) -> dict:
    """Hoist the invariant part of the key and nest the rest as series.

    A row-per-observation frame repeats the whole key on every row, which on a
    16-dimension flow costs ~450 redundant bytes an observation. Empty
    observations are dropped rather than serialised: NaN is not valid JSON, and
    a daily series is roughly a third weekends.

    `cap` is the per-series bound the provider was given, when it was given
    one. It is what makes `total` a floor rather than a count, so it has to
    reach the response text.

    `asked` is the key the caller sent. It is only used when nothing came back,
    because the key is otherwise derived from the frame and an empty frame has
    no columns to derive it from: the response then said nothing about what had
    just been asked for. `names` maps each dimension's codes to labels, and
    only the codes that appear are returned.
    """
    at_cap = _at_cap(df, cap, units)
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
    if shown < total or at_cap:
        per = ("" if len(groups) == 1 else
               f", at most {max(shares, default=0)} per series")
        out["truncated"] = (
            f"most recent {shown} of at least {total}{per}; only the newest "
            f"{cap} per series were fetched, so total is a floor rather than "
            "the series length — narrow start/end for the rest"
            if at_cap else
            f"most recent {shown} of {total}{per}; narrow start/end for the rest")
    if dropped:
        out["dropped_series"] = {"count": len(dropped),
                                 "keys": [_split(k, units)[0] for k in dropped[:10]]}
    if empty:
        out["empty"] = empty

    if names:
        seen = {}
        for k in [hoisted, *(_split(k, units)[0] for k, _ in tails)]:
            for dim, code in k.items():
                seen.setdefault(dim, set()).add(code)
        labelled = {dim: {c: names[dim][c] for c in sorted(cs) if c in names[dim]}
                    for dim, cs in seen.items() if dim in names}
        labelled = {dim: got for dim, got in labelled.items() if got}
        if labelled:
            out["names"] = labelled

    if not total:
        # Nothing matched, so there is no frame to read the key off and the
        # response would otherwise not say what had been asked for. Every
        # cause looks the same from here, which is the reason for the note:
        # a code the flow does not carry, a period the series does not cover
        # and one empty code in a multi-code key are indistinguishable.
        out["key"] = {k: str(v) for k, v in (asked or {}).items()}
        out["note"] = (
            "no observations. Any one entry in the key can empty the result, "
            "and so can a period the series does not cover; they look the same "
            "from here. Leave a dimension out of the key to see what the flow "
            "carries for the rest, or check a code with search_codes."
            if not empty else
            "the key matched, but every observation in the period is empty.")
    return out


GENERIC = {"Accept": "application/vnd.sdmx.genericdata+xml;version=2.1"}

# Providers observed to serve structure-specific data referencing a DSD sdmx1
# cannot resolve. BIS is the one that does today, and asking it the default way
# costs a whole download and parse before failing — on the provider the README
# leads with. Learned rather than listed: a hardcoded set has to be right about
# providers nobody has tried, and it is not safe to guess in either direction.
# IMF_DATA answers 500 to the generic Accept header, so a wrong entry does not
# merely waste a header, it takes the provider down for this client. Nothing is
# ever added here except by having failed.
_NEEDS_GENERIC: set[str] = set()


def _data(provider: str, flow: str, key: dict, params: dict):
    if provider in _NEEDS_GENERIC:
        return _client(provider).data(flow, key=key, params=params, headers=GENERIC)
    try:
        return _client(provider).data(flow, key=key, params=params)
    except sdmx.exceptions.XMLParseError:
        msg = _client(provider).data(flow, key=key, params=params, headers=GENERIC)
        _NEEDS_GENERIC.add(provider)  # only after the generic form has worked
        return msg


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


# Providers that will not take lastNObservations. Learned rather than listed,
# for the reason _NEEDS_GENERIC is, but the cost of a wrong guess runs the other
# way: a refused request is a cheap error page and the retry is the full
# download, where a wrong generic header wastes the download first. So the cap
# goes to everyone until a provider refuses it.
_NO_LAST_N: set[str] = set()


def _refused(exc) -> bool:
    """Whether the service rejected the request rather than failed to serve it.

    A 4xx that is not 429 is this client having composed something the provider
    would not accept, which is what an unsupported parameter looks like. A 5xx
    has already been retried in transport and says the service is unwell, so
    dropping the cap would not help and remembering it would be wrong.
    """
    r = getattr(exc, "response", None)
    return r is not None and 400 <= r.status_code < 500 and r.status_code != 429


def _observations(msg) -> int:
    """How many observations a data message carries, at either level."""
    n = 0
    for ds in getattr(msg, "data", []) or []:
        n += len(getattr(ds, "obs", []) or [])
        for obs in (getattr(ds, "series", {}) or {}).values():
            n += len(obs)
    return n


def _bounded(provider: str, send, params: dict, cap: int):
    """Fetch, asking for only the newest `cap` observations per series.

    Returns the message and the cap that shaped it, or None where the provider
    was asked without one. `limit` used to bound the response after the whole
    history had been downloaded and parsed: BIS shipped 314KB, ECB 1.4MB and
    Bundesbank 2.3MB to answer questions about the last three observations.
    Asking the service to do the truncating costs a query parameter and returns
    3-10KB. It buys nothing on a query that was already narrow.

    An empty response is checked rather than believed. A service that answers
    200 to a parameter it does not understand looks exactly like a query that
    matched nothing, and the difference matters: one is a wrong answer and the
    other is the right one. The uncapped request settles it, and is cheap in
    the case that it is genuinely empty.

    So is the series count, and for a worse reason. ILO answers a capped
    request for its US consumer price flow with 13 series where 39 exist,
    losing two thirds of them with a 200 and no truncation to show for it. The
    empty check does not see that: the response has data, it is simply not all
    of the data. Nothing in a capped response reveals it either, since a
    provider is entitled to return fewer observations and this one returns
    fewer *series*. The only way to know is to count them another way, so the
    first capped fetch of a provider is checked against a `detail=nodata`
    request, which returns the keys and no observations. One extra request per
    provider per process, and it is the difference between bounding a download
    and quietly dropping data.
    """
    if provider in _NO_LAST_N:
        return send(params), None
    try:
        msg = send({**params, "lastNObservations": cap})
    except Exception as exc:
        if not _refused(exc):
            raise
        msg = None
    if (msg is not None and _observations(msg)
            and _keeps_series(provider, send, params, msg, cap)):
        return msg, cap
    bare = send(params)
    if _observations(bare):
        _NO_LAST_N.add(provider)  # only once the cap has been shown to cost data
    return bare, None


# The smallest cap at which a provider has been shown to return every series
# the key matches. Not a plain set, because ILO's answer depends on the number
# asked for: 39 series at 2001, 13 at 501, 2 at 5. Asking for more observations
# cannot return fewer series, so a verdict holds for any cap at least as large
# as the one it was measured at, and a smaller one has to be measured again.
# Recording it as a set would let one fetch at limit=2000 certify a provider
# that loses two thirds of its series at the default limit of 500.
_KEEPS_SERIES: dict[str, int] = {}


def _series(msg) -> int:
    return sum(len(getattr(ds, "series", {}) or {})
               for ds in getattr(msg, "data", []) or [])


def _keeps_series(provider: str, send, params: dict, capped, cap: int) -> bool:
    """Whether the cap returned every series the key matches.

    `detail=nodata` asks for the keys without the observations, so on a
    provider that honours it the check costs a fraction of the data. On one
    that ignores it the check costs what the uncapped request would have, which
    is the price of finding out. A provider that cannot answer it at all is
    treated as unsafe: the alternative is to assume the capped answer is whole,
    which is the assumption that lost ILO its series.
    """
    if cap >= _KEEPS_SERIES.get(provider, float("inf")):
        return True
    try:
        keys = send({**params, "detail": "nodata"})
    except Exception:
        _NO_LAST_N.add(provider)
        return False
    if _series(keys) > _series(capped):
        _NO_LAST_N.add(provider)
        return False
    _KEEPS_SERIES[provider] = min(cap, _KEEPS_SERIES.get(provider, cap))
    return True


def fetch(provider: str, flow: str, key: dict, start: str | None = None,
          end: str | None = None, limit: int = 500) -> dict:
    if provider in NATIVE:
        adapter = NATIVE[provider]
        units = getattr(adapter, "UNITS", ())
        df = adapter.frame(flow, key, start, end)
        dims = [c for c in df.columns
                if c not in ("TIME_PERIOD", "value") and c not in units]
        return _pack(df, limit, units, asked=key,
                     names=_native_labels(adapter, flow, dims))
    params = {}
    if start:
        params["startPeriod"] = start
    if end:
        params["endPeriod"] = end
    send = ((lambda p: bundesbank.data(flow, key, p)) if provider == "BBK" else
            (lambda p: _data(provider, flow, key, p)))
    # One more than the budget, so a series that outruns it still arrives long
    # enough to say so. Asked for exactly `limit`, a truncated series would be
    # indistinguishable from a complete one and the response would report no
    # truncation at all.
    msg, cap = _bounded(provider, send, params, limit + 1)
    df, units = _frame(msg, provider, flow)
    return _pack(df, limit, units, cap, asked=key,
                 names=_dim_labels(provider, flow))
