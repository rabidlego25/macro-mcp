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
  a silent error, so the convention is a required argument, not a default. The
  ECB quotes everything against the euro, so a pair without EUR is a cross
  derived from two fixings; the response says so rather than presenting it as a
  published rate.
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
| `fx_spot` | One day's ECB euro reference rate, marked when derived |
| `fx_period_rate` | Average or end-of-period rate, in the same shape as `fetch_data` |

The same restraint applies to data. A flat row per observation repeats the whole
key on every row, which on a 16-dimension flow is around 450 wasted bytes an
observation, so `fetch_data` hoists the invariant part of the key, groups the
rest into series and returns `[period, value]` pairs. A year of daily Bund
yields goes from 173KB to 6KB.

```json
{
  "key": {"FREQ": "M"},
  "units": {"UNIT_MEASURE": "Per cent per year", "UNIT_MULT": "Units"},
  "columns": ["period", "value"],
  "series": [{"key": {"REF_AREA": "JP"}, "observations": [["2024-01", -0.1]]}],
  "range": ["2024-01", "2024-12"], "total": 24
}
```

## Units

A bare `634751300000000.0` is not an answer to what Japan's GDP was — it is
¥634.75tn or ¥634.75bn depending on a multiplier the provider ships and `sdmx1`
discards unless asked. So `fetch_data` returns what the number is measured in,
resolved from the provider's code to its label: BIS sends `UNIT_MEASURE="368"`,
which is no more use than the number was.

Providers spell it differently and attach it at different levels — BIS and ILO
write `UNIT_MEASURE`/`UNIT_MULT`, ECB adds `UNIT_INDEX_BASE`, Bundesbank
prefixes its own `BBK_UNIT`, IMF publishes no unit at all but does populate
`SCALE`, and Singapore states one per row — so units are matched by pattern
rather than by a list, at whatever level they arrive.

They are returned beside the key, never inside it: a unit is not a dimension,
and an agent that echoed one back to `fetch_data` would get an error from the
provider. A unit that is invariant across the response is hoisted once; one
that varies lands on each series, so a response mixing percent with an index
says so instead of interleaving the two silently.

Nothing else a provider attaches is returned. BIS ships around 2.5KB of
compilation notes and source references per series, against a response format
whose whole point is 6KB.

`range` is the span actually returned, so truncation is visible rather than
inferred from a `total` that does not match. Truncation keeps the most recent
observations, and `limit` is shared across the series in the response rather
than spent oldest-first over the whole of it — otherwise a two-country request
came back with only the country whose history ran latest. The split is max-min
fair, so a short series hands its unused share to a long one and a response that
fits under the budget is never clipped. Where there are more series than the
budget can seat, the ones left out are named under `dropped_series` instead of
going missing. Periods with no value are omitted and counted under `empty`.

`limit` bounds the download as well as the response. The provider is asked for
only the newest `limit + 1` observations per series, through SDMX's own
`lastNObservations`. Three observations cost 10KB from BIS rather than 314KB,
3KB from ECB's daily reference rates rather than 1.4MB, and 4KB from the
Bundesbank 10-year Bund yield rather than 2.3MB; twelve months of Japanese CPI
cost 53KB and 4.4s from IMF rather than 1.5MB and 12.1s.

The extra one is what keeps truncation visible: asked for exactly `limit`, a
clipped series comes back the same length as a complete one. When a series does
arrive at the cap, `total` is a floor rather than the length of the series, and
the `truncated` note says so — counting the rest would mean downloading it.

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

## Pacing and retries

Every request goes through one transport adapter that bounds how hard a
provider is asked and absorbs the failures that are not answers.

- **Per host, not per provider.** Four requests in flight at once by default,
  and no delay. HKMA is the exception at one at a time, 4/s: it started
  answering 502 on every path after eight parallel requests and did not recover
  for minutes.
- **Transient statuses are retried** — 429, 500, 502, 503, 504 — three attempts
  with exponential backoff and jitter, so ISTAT's intermittent 500s no longer
  reach the agent as errors. A 404 is an answer and is not repeated, and
  neither is a TLS failure — UY110's self-signed certificate will not verify on
  the second attempt either.
- **`Retry-After` is honoured, and held against the whole host.** A 429 is
  addressed to this client rather than to the request that drew it, so
  everything queued behind it waits too.

The adapter sits below the cache, so a cached read neither waits nor spends a
slot. The state is per process: two servers on one machine do not coordinate,
and the shared User-Agent means a provider throttling it throttles every
install at once.

## Tests

```bash
uv run pytest                                        # offline, ~1s
MACRO_MCP_LIVE=1 uv run pytest -m "not revisable"    # + structure, ~70s
MACRO_MCP_LIVE=1 uv run pytest -m revisable          # what the data did
```

The live suite is split because its two halves mean opposite things. Unmarked
tests assert structure — a flow exists, a key resolves, a period joins — and a
failure means a provider moved or this server broke. Tests marked `revisable`
assert that a number is still the number it was, and a failure there means a
CPI was rebased or a national account revised: the provider doing its job, and
the event this project exists to surface. They run as separate CI jobs, and
only the first can fail the build.

The offline suite replays saved responses in `tests/fixtures/`. Every case in it
was a real failure, and each asserts a value rather than the absence of an
exception, because these paths fail by returning a plausible wrong answer with a
200 status rather than by raising.

The live suite pins historical values, so a failure means a provider moved,
renamed something, or revised a series.

## Current problems and limitations

Defects and constraints in this server, as distinct from properties of the data
(below) and gaps in provider coverage (further below). Roughly worst first.

- **Observations are never cached, so every fetch pays full price.** That is
  deliberate — see Caching — but it means repeated identical queries re-download
  each time. It bites hardest on HKMA: a bound coarser than the endpoint's own
  period cannot be sent to the service, so the adapter pulls the full history
  (up to 6,302 rows) and filters locally, on every call.
- **`sdmx1` cannot query SDMX 3.0 data.** It builds `?c=TIME_PERIOD` instead of
  `c[TIME_PERIOD]=ge:…`, puts the source id where the agency belongs in the
  path, and raises `TypeError: unhashable type: 'MemberValue'` when a key is
  passed as a dict. Nothing hits this today because IMF is wired to its 2.1
  endpoint, but the first genuinely 3.0-only provider will need an adapter.
- **Point-in-time is IMF-only.** No other provider here republishes vintages, so
  `compare_vintages` cannot answer the question anywhere else. It also spends its
  request budget before it knows which vintages carry the key, so asking for five
  can leave fewer readable; those appear under `no_data` rather than being topped
  up, since the alternative is an unbounded number of calls to a slow service.
- **HKMA datasets are searchable only by slug.** It publishes no titles through
  the API, so `find_dataflows` matches `hk-interbank-ir-daily` and not the words
  a person would use for it. Its quarterly datasets also report the month the
  quarter ended (`2024-03`), which is indistinguishable from a monthly period
  when joined against another provider.
- **The disk cache only grows.** Entries expire after a week but nothing prunes
  or vacuums the SQLite file, which reached 96MB here across a few live runs.
  Delete `$XDG_CACHE_HOME/macro-mcp` when it gets large.
- **Pacing is per process and the User-Agent is shared.** Two servers on one
  machine, or two installs anywhere, do not coordinate, so the limits in
  `transport.HOSTS` bound one client rather than the traffic a provider
  actually sees. Nothing here can fix that; a hosted deployment would have to.
- **A paced host is a slow host.** HKMA is asked one request at a time, so
  reading several of its datasets in one turn now costs at least 250ms each
  rather than going out together. That is the trade the 502s bought.
- **The offline suite still misses two layers.** GLEIF has no offline test at
  all, and `server.py` — every tool signature and docstring an agent actually
  reads — has none either, so nothing checks the contract the agent is handed.
  The nine fixtures cover Bundesbank, HKMA and Singapore: the three adapters
  that are exceptions to the SDMX spine. The spine that 27 of 29 providers
  traverse has no recorded response anywhere in the repo, so its tests are
  either live or stubbed.
- **The download is capped per series, not per response.** `lastNObservations`
  bounds each series the key matches, so a wildcard over 300 series still
  fetches `limit + 1` observations for every one of them. `limit` bounds what
  comes back; only the key bounds what is fetched.
- **`total` is a floor once the cap binds.** It used to be the length of the
  series, which was free only because the whole series had been downloaded.
  Now it counts what arrived, and a series that came back at the cap has older
  observations nobody counted. The `truncated` note says which of the two it
  is; there is no way to report the exact length without paying for it again.
- **Not every provider honours the cap.** It is sent to all of them. BIS, ECB,
  IMF, Bundesbank, OECD and ILO truncate at the source; UNSD and UNICEF
  returned the same bytes with the parameter as without, so they appear to
  ignore it and still ship the whole series. None refused it, but one that does
  is asked again without it and remembered for the life of the process.
- **A query that matches nothing costs two requests.** A service that answers
  200 to a parameter it does not understand looks exactly like a key that
  matched nothing, so an empty capped response is checked against an uncapped
  one before it is believed. Both are cheap when the query really is empty, but
  `compare_vintages` pays it once per vintage that does not carry the key.
- **A narrow query gains nothing from the cap and pays a little.** It bounds
  the history, so a key already pinned to one series inside a one-year window
  is the same size either way: comparing four vintages of Japanese GDP moves
  21.3KB of observations before the cap and 25.3KB after, the difference being
  the extra request above.
- **Nothing bounds the structure metadata, which is the larger half.** That
  same vintage comparison spends 31MB on five DSDs of around 3.5MB each against
  21KB of observations. It is paid once a week rather than once a call — see
  Caching — but on a cold process the download cap addresses the smaller part
  of the bill.
- **The cap does not reach the non-SDMX adapters.** Singapore and Hong Kong
  have no such parameter, so `limit` still bounds only their responses.
- **`limit` binds evenly, not by importance.** The budget is split max-min
  fair across the series in a response, so nothing is clipped while there is
  room and a short series hands its surplus to a long one. Once it does bind,
  though, every long series is cut to the same depth regardless of which one the
  question was about, and a response with more series than the budget can seat
  drops the excess — named under `dropped_series`, but dropped. Narrow
  `start`/`end`, or raise `limit`, when querying several series at once.
- **The first BIS fetch of a session pays for a failed parse.** BIS serves
  structure-specific data referencing a DSD `sdmx1` cannot resolve, so the
  payload is downloaded and parsed once before the generic form is tried. The
  provider is remembered after that and every later fetch goes generic-first,
  but the knowledge dies with the process, and `sdmx1` prints its parse stack
  and the failing element to stdout on the way — the MCP SDK claims that
  descriptor and diverts it to stderr, so it is noise rather than corruption.
  Not hardcoded to BIS on purpose: IMF answers 500 to the generic header, so a
  wrong guess would take a provider down rather than waste a header.
- **Units are only as good as the provider's own metadata.** HKMA states none
  at all, so its numbers come back bare. Bundesbank labels its unit in German
  (`PROZENT`) because the English one is published as an empty element, and its
  multiplier resolves to a raw `0` because no `CL_BBK_UNIT_MULT` codelist is
  served. A raw code is left in place rather than guessed at.
- **Resolving a unit code needs the flow's structure.** `fetch_data` now reads
  the DSD to turn `368` into "Per cent per year", so a cold fetch against a
  provider whose structures are slow — ISTAT is 29s cold — pays for that
  metadata once a week. `describe_flow` has usually already warmed it, since the
  prescribed order goes through it.
- **The non-SDMX adapters expose a single dimension.** Singapore and Hong Kong
  return one wide table per dataset, so `SERIES` is the only thing to slice on.
  There is no `REF_AREA` to filter, because there is no country dimension.
- **`sdmx1` emits a `DeprecationWarning` from its own internals** (it passes a
  deprecated `provider=` to itself). Left visible rather than filtered, since
  suppressing it would also hide the same warning if it came from here.

## What it will not do for you

Properties of the data itself. The server surfaces these; it does not silently
fix them.

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

What is not covered, and why.

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
