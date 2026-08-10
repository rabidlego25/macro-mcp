# macro-mcp

MCP server for international macro statistics, company identity and FX rates.
Every source is free and keyless.

## Why

Most finance MCP servers wrap one API with one tool per endpoint. That does not
survive going international: there is no global EDGAR, no shared company key, and
each provider codes countries differently. This takes a different route.

- **One grammar, many providers.** SDMX is ISO 17369, and the BIS, ECB, IMF, OECD,
  Eurostat, World Bank, ILO and a dozen national offices all publish through it.
  One set of tools reaches all of them. Sources that do not speak SDMX are adapted
  to the same grammar rather than given tools of their own: Singapore's Table
  Builder is plain JSON, but a table becomes a dataflow, its rows become one
  dimension's codes, and its periods are rewritten from `2024 Jan` to `2024-01`
  so they join against everything else.
- **LEI as the join key.** GLEIF covers 2.8M entities across 200+ jurisdictions,
  free, including the ownership graph. Tickers and CIKs do not travel.
- **Rate conventions are explicit.** Converting flows at an end-of-period rate is
  a silent error, so the convention is a required argument, not a default.
- **No translation layer.** SDMX names are multilingual and providers ship English
  in the same response, so search matches every localization and returns English
  where it exists. `crops` finds ISTAT's `Coltivazioni`; `chomage` finds INSEE's
  unemployment series. Entity names come from GLEIF's registered alternative-language
  name, which is a legal fact rather than a translation.

## Install

```bash
uv sync
```

Register with an MCP client:

```json
{
  "mcpServers": {
    "macro": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/macro-mcp", "macro-mcp"]
    }
  }
}
```

## Tools

Discovery is progressive — a single codelist can hold hundreds of entries, so
metadata is never returned whole.

| Tool | Purpose |
|---|---|
| `list_providers` | Providers by region, with quirks and metadata support |
| `find_dataflows` | Search a provider's dataflows |
| `describe_flow` | Dimensions with code counts and a sample |
| `search_codes` | Resolve one dimension's codes, including country codes |
| `fetch_data` | Observations for a dimension key, as compact series |
| `list_vintages` | Releases of a dataflow, oldest first |
| `compare_vintages` | One key across vintages, with the revisions between them |
| `find_entity` | GLEIF search by legal name |
| `get_entity` | Look up one LEI |
| `entity_ownership` | Direct parent, ultimate parent, direct children |
| `fx_spot` | Daily ECB reference rate |
| `fx_period_rate` | Average or end-of-period rate |

The same restraint applies to data. A flat row per observation repeats the whole
key on every row, which on a 16-dimension flow is around 450 wasted bytes an
observation, so `fetch_data` hoists the invariant part of the key, groups the
rest into series and returns `[period, value]` pairs. A year of daily Bund
yields goes from 173KB to 6KB.

```json
{
  "key": {"FREQ": "M"},
  "columns": ["period", "value"],
  "series": [{"key": {"REF_AREA": "JP"}, "observations": [["2024-01", -0.1]]}],
  "range": ["2024-01", "2024-12"], "total": 24
}
```

`range` is the span actually returned, so truncation is visible rather than
inferred from a `total` that does not match. Truncation keeps the most recent
observations. Periods with no value are omitted and counted under `empty`.

## Point in time

A series read today is as-revised, not as-known, which quietly gives a backtest
numbers nobody had at the time. IMF republishes whole dataflows as monthly
vintages beside the current one, so `compare_vintages` can read the same key
from each and report what moved:

```json
{"period": "2024", "was": 634226000000000.0, "now": 634751300000000.0,
 "between": ["ANEA_2026_APR_VINTAGE", "ANEA"], "change_pct": 0.0828}
```

Japan's 2024 nominal GDP, revised up by ¥525.3bn since the April 2026 vintage.
Coverage varies between vintages as well as values — one 2026 vintage of the
national accounts carries 18,068 observations and another 204 — so a vintage
that does not have the key is listed under `no_data` rather than counted as
agreeing with its neighbours.

## Caching

Metadata is cached to disk under `$XDG_CACHE_HOME/macro-mcp` for a week.
Structures are large and slow to build — ISTAT takes 29s cold and 1.5s warm,
Eurostat 52s and 11s — and providers republish them rarely. In-process
memoisation alone threw all of that away when the server exited.

Nothing else is cached. The policy denies by default and names the structure
endpoints it will keep, rather than naming the data paths it will skip. That
ordering matters: the first version listed the data paths, and Singapore's
`/tabledata/` was not among them, so observations would have been served up to a
week stale. Under default-deny, an adapter whose paths nobody declared costs a
round trip instead of correctness.

The data patterns are declared first because the first match wins and BIS puts
`/data/dataflow/` in its *data* URLs, which the structure patterns would
otherwise claim. Set `MACRO_MCP_NO_CACHE=1` to bypass caching entirely.

## Tests

```bash
uv run pytest                      # offline, ~0.2s
MACRO_MCP_LIVE=1 uv run pytest     # adds the network suite, ~30s
```

The offline suite replays saved responses in `tests/fixtures/`. Every case in it
was a real failure, and each asserts a value rather than the absence of an
exception, because these paths fail by returning a plausible wrong answer with a
200 status rather than by raising.

The live suite pins historical values, so a failure means a provider moved,
renamed something, or revised a series.

## What it will not do for you

The server surfaces these; it does not silently fix them.

- Geo codelists mix aggregates and members (EU27 next to France). Summing both
  double-counts, and nothing errors.
- Nominal, PPP and constant-price series are not interchangeable.
- Fiscal years differ. India, Japan and Australia are not calendar-year.
- Seasonal adjustment differs: X-13 in the US, TRAMO/SEATS across much of Europe.
- Most providers publish revisions without point-in-time access, so history reads
  as-revised rather than as-known. IMF is the exception, and `compare_vintages`
  reads it; everywhere else the caveat still stands.
- Entity search matches broadly and may rank a subsidiary above its parent. Hits
  carry country and status; use `entity_ownership` to walk up the group.

## Known gaps

- **Asian national sources are mostly gated.** Headline macro for Asia is already
  covered by the international providers — BIS carries all of JP, CN, IN, KR, SG,
  HK, TW, TH, MY, ID, PH, VN, PK and BD for policy rates and property prices, and
  the IMF, World Bank and ILO are comparably broad. What is missing is national
  detail, and there the constraint bites: e-Stat (Japan), ECOS (Korea), KOSIS and
  data.gov.in all require registration, so they cannot be included while the
  project stays keyless. Singapore is in via `SINGSTAT` and Hong Kong via
  `HKMA`. Malaysia's OpenDOSM (`api.data.gov.my`) is keyless and works, but
  exposes no catalogue endpoint at all, so dataset ids would have to be invented
  from the documentation rather than derived from it.
- **HKMA's dataset list is a snapshot.** HKMA publishes no catalogue endpoint,
  so the 125 datasets in `hkma.py` were read off the documentation and then
  verified one request each against the live API. That table goes stale as HKMA
  adds and retires datasets; a retired one is reported as such rather than as a
  bare 404. Regenerate it with
  `uv run python -m scripts.hkma_catalogue`.
- **IMF publishes three endpoints and only one serves data.** `sdmx1` ships
  `IMF` (sdmxcentral, which answers 501 on data), `IMF_DATA` (SDMX 2.1) and
  `IMF_DATA3` (SDMX 3.0). The 3.0 service returns structures but a header and one
  empty row for every flow, so `IMF_DATA` is the one wired up. Its dimensions
  carry no local representation — codes are reachable only through the concept
  each dimension identifies — and it writes monthly periods as `2024-M01`, which
  is rewritten to `2024-01` so the series joins against everything else.
- **Endpoints drift.** `sdmx1` hardcodes base URLs that go stale as institutions
  move. `URL_FIXES` corrects ABS (the old host stopped resolving) and Lithuania
  (moved to an APEX path); `AGENCY` corrects INEGI, whose flows are filed under a
  different agency id. Re-verify these if a provider starts failing.
- **Bundesbank needs its own adapter** (`bundesbank.py`). It serves valid SDMX-ML
  from non-standard paths, writes URNs missing their class segment, publishes
  codelists separately from the DSD, and returns 100MB+ for an unpinned query.
- **Genuinely down:** DG COMP 404s on every path and Uruguay serves a self-signed
  certificate. ISTAT returns intermittent 500s. See `QUIRKS`.
- **WB_WDI, StatCan, NBB and AR1** serve data but not dataflow metadata, so flow
  ids must be known in advance. `list_providers` flags this. Which providers
  serve what is measured, not assumed: `sdmx1`'s own capability table is a static
  declaration that disagrees with the live services in both directions. Regenerate
  the measured one with `MACRO_MCP_NO_CACHE=1 uv run python -m scripts.probe`,
  which retries once so a dropped connection is not recorded as a missing endpoint.
- **Filings** are out of scope. There is no free global equivalent until ESAP
  opens its API in July 2027.
