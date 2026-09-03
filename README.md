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

Nothing to clone and no keys to obtain. Point an MCP client at the repository
and [uv](https://docs.astral.sh/uv/) does the rest:

```json
{
  "mcpServers": {
    "macro": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/rabidlego25/macro-mcp", "macro-mcp"]
    }
  }
}
```

`uvx` resolves and caches the environment on the first run, and that run is
slow: four minutes and 306MB here, nearly all of it downloading pandas and
lxml. Every start after it was under two seconds. Run the command once in a
terminal before registering it, since a client that starts servers with a
timeout will give up long before the first one finishes.

To work on the server rather than use it, clone and run from the checkout:

```bash
uv sync
```

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

Discovery is progressive: a single codelist can hold hundreds of entries, so
metadata is never returned whole.

| Tool | Purpose |
|---|---|
| `list_providers` | Providers by region, with quirks and metadata support |
| `find_dataflows` | Search a provider's dataflows, or every provider with `"*"` |
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

## Search

`find_dataflows` matches every word of the query, in any order, against the id
and every localization a provider publishes. Matching the phrase as one
substring asked IMF for "national accounts" and found one flow, hiding `ANEA`,
whose name is "National Economic Accounts (NEA), Annual Data".

What matched is then ordered, because a hundred names is not a narrower answer
than a catalogue. ILO answers "unemployment" with 108 flows and used to put the
headline rate 66th, behind sixty-five breakdowns of itself. A dataflow name is a
subject followed by the breakdowns applied to it, so four things rank it: an
exact match on a name or id, then whether the query's words begin words rather
than land inside them, then how far into the name the last of them appears, then
length.

Each is there for a case. The word-start test keeps "employment" from ranking
"time-related underemployment" alongside "Employment by sex", and anchors only
the front, since anchoring the end too would cost `WS_CBPOL` its one hit for
"policy rate" over "Central bank policy rates". Position separates a name that
leads with the subject from one that mentions it in passing. Length is what
picks the headline series out of its own breakdowns: "Unemployment rate by sex
and age" over "Unemployment rate by sex, age and marital status". It also, for
free, puts IMF's current `CPI` above the four monthly vintages of itself, whose
names are its name with a date appended.

Nothing is dropped and `total` still counts every match. Where the shown list is
cut, a `note` says it is the closest ones and that a further word will narrow
it, so the next move is a word rather than a guess. Without a search term there
is nothing to be close to, and the note says the order is arbitrary instead of
claiming one.

### Which provider has it

Ordering only helps once you have picked a provider. Asking the wrong one
returns a zero that is true and useless: `find_dataflows("IMF_DATA",
"unemployment")` is `total: 0`, and ILO has 108. So `provider="*"` searches
every catalogue at once and answers with providers rather than flows.

```json
{"search": "unemployment", "total": 294, "index_built": "2026-09-02",
 "providers": [
   {"provider": "ISTAT", "region": "national_eu", "flows": 24,
    "sample": [{"id": "151_929", "name": "Unemployment"}]},
   {"provider": "ILO", "region": "international", "flows": 108,
    "sample": [{"id": "DF_UNE_DEAP_SEX_AGE_RT", "name": "Unemployment rate by sex and age"}]}]}
```

Providers are ordered by their best hit rather than by how many they have,
because five hundred loose matches is a worse answer than one flow named
exactly what was asked for. Each carries its region, which is the difference a
routing question turns on: ILO covers 190 countries and ISTAT covers Italy, and
nothing else in the response says so. A search that matches nothing in one
provider gets the same list under `elsewhere`, unasked, since that response had
nothing else in it.

This cannot be a live fan-out. Reading twenty catalogues costs 63s from
Eurostat and 51s from ISTAT on a cold cache, and no tool call is two minutes.
So the catalogues are read once by `scripts/catalogue.py` and shipped as ids
and names only: 27,190 flows across 20 providers, 5.3MB of JSON and 767KB
gzipped, against a wheel that already pulls 306MB of pandas. Loading it costs
25ms once per process and a search over it 45ms.

Which makes it a snapshot, and snapshots rot. The design point is that it never
answers anything: it says where to look, the flow it names is confirmed with a
normal `find_dataflows` against that provider, and the response says so and
carries the date it was built. A stale index can misroute and cannot return a
stale number — the same default-deny reasoning the cache uses. Four live tests
sample it against the providers, so drift fails the build rather than surfacing
as a bad suggestion.

Two ways of not building it were tried first. The SDMX Global Registry is
genuinely cross-agency and holds about a hundred dataflows, mostly Eurostat
stubs, against ILO's 1,212 here: it registers what organisations choose to
publish there, not what they serve. DBnomics does have a live cross-provider
search over ~96 providers, and its ids are its own — it calls Eurostat
`Eurostat` where this calls it `ESTAT`, and ILO's flow `UNE_TUNE_SEX_AGE_EDU_NB`
where ILO serves `DF_UNE_TUNE_SEX_AGE_EDU_NB`. A hit there does not give an
agent a key it can use here, which is the only thing a routing answer is for.

## Units

A bare `634751300000000.0` is not an answer to what Japan's GDP was. It is
¥634.75tn or ¥634.75bn depending on a multiplier the provider ships and `sdmx1`
discards unless asked. So `fetch_data` returns what the number is measured in,
resolved from the provider's code to its label: BIS sends `UNIT_MEASURE="368"`,
which is no more use than the number was.

Providers spell it differently and attach it at different levels. BIS and ILO
write `UNIT_MEASURE`/`UNIT_MULT`, ECB adds `UNIT_INDEX_BASE`, Bundesbank
prefixes its own `BBK_UNIT`, IMF publishes no unit at all but does populate
`SCALE`, and Singapore states one per row. So units are matched by pattern
rather than by a list, at whatever level they arrive.

They are returned beside the key, never inside it: a unit is not a dimension,
and an agent that echoed one back to `fetch_data` would get an error from the
provider. A unit that is invariant across the response is hoisted once; one
that varies lands on each series, so a response mixing percent with an index
says so instead of interleaving the two silently.

Nothing else a provider attaches is returned. BIS ships around 2.5KB of
compilation notes and source references per series, against a response format
whose whole point is 6KB.

`names` gives the English label for every code in the response, so a series
keyed `XDC` or `CP01` reads without another round trip. It comes off the
structure the units already needed, and only the codes that actually appear are
returned. `range` is the span actually returned, so truncation is visible
rather than inferred from a `total` that does not match. Truncation keeps the most recent
observations, and `limit` is shared across the series in the response rather
than spent oldest-first over the whole of it. Otherwise a two-country request
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
the `truncated` note says so: counting the rest would mean downloading it.

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
Coverage varies between vintages as well as values. One 2026 vintage of the
national accounts carries 18,068 observations and another 204, so a vintage
that does not have the key is listed under `no_data` rather than counted as
agreeing with its neighbours.

## Caching

Metadata is cached to disk under `$XDG_CACHE_HOME/macro-mcp` for a week.
Structures are large and slow to build (ISTAT takes 29s cold and 1.5s warm,
Eurostat 52s and 11s) and providers republish them rarely. In-process
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
- **Transient statuses are retried.** 429, 500, 502, 503 and 504 get three
  attempts with exponential backoff and jitter, so ISTAT's intermittent 500s no
  longer reach the agent as errors. A 404 is an answer and is not repeated, and
  neither is a TLS failure: UY110's self-signed certificate will not verify on
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
tests assert structure (a flow exists, a key resolves, a period joins) and a
failure means a provider moved or this server broke. Tests marked `revisable`
assert that a number is still the number it was, and a failure there means a
CPI was rebased or a national account revised: the provider doing its job, and
the event this project exists to surface. They run as separate CI jobs, and
only the first can fail the build.

The offline suite replays saved responses in `tests/fixtures/`. Every case in it
was a real failure, and each asserts a value rather than the absence of an
exception, because these paths fail by returning a plausible wrong answer with a
200 status rather than by raising.

One test spawns the server as its own process and speaks JSON-RPC to it over
stdin, which is the only thing that covers `main()`, the stdio transport and
the handshake. It is how the empty `serverInfo.version` was found. The rest of
the tools are exercised through `call_tool`, not by calling the functions
underneath, so argument validation, the published schema and the JSON an agent
actually parses are all in the path. What those tools publish is asserted
literally: the names, which arguments may be omitted, what they then default
to, and the docstrings themselves. Every part of it can drift from the code
beneath without failing anything else.

The recorded responses are mounted under a real `sdmx1` session rather than fed
to the parser directly, so a test drives URL construction, the Accept header,
`sdmx1` and the packing here together. That is where several of the failures
were: an SDMX key is positional, so getting the dimension order wrong returns
somebody else's series with a 200 status. ECB stands in for the spine that 27
of the 29 providers traverse; Bundesbank, Hong Kong, Singapore and BIS have
fixtures of their own because each is an exception to it.

The live suite pins historical values, so a failure means a provider moved,
renamed something, or revised a series.

## Evals

Twenty questions a person would actually ask, run through the tools against
live providers, with every call and response kept in `evals/log`. Thirteen were
answered, three partly, four blocked, one of those because HKMA was down.

Almost nothing crashed. The server returned 200 and a well-formed response and
the agent was stuck anyway, which is the failure this project is about: an
empty result that echoed nothing back, a 15-digit GDP figure with no currency
attached, a search for "national accounts" that reported one hit and hid the
flow, a search for unemployment that returned 108 flows with the headline rate
66th of them, and a search for Banco Santander led by an unrelated company that
matched the city. Eight of the fourteen findings are fixed and verified against
the live providers; `evals/README.md` lists what was fixed, what was only
improved, and what still stands.

## Current problems and limitations

Defects and constraints in this server, as distinct from properties of the data
(below) and gaps in provider coverage (further below). Roughly worst first.

The first six came out of an adversarial review of the coverage analysis on
2026-09-03, which went looking for what the search and index work had got wrong
and found more in the server than in the analysis. Each was reproduced here
before being written down.

- **LSD serves 9,156 dataflows and not one of them fetches.** Every flow tried
  raises `TypeError: unhashable type: 'MeasureDimension'` from inside `sdmx1`,
  before this code sees a response, so it reaches the agent as a crash rather
  than an error (6 of 6 random flows, 2026-09-03). It is the largest catalogue
  here, larger than Eurostat's, and `list_providers` advertises it as fully
  capable: `scripts/probe.py` records `datastructure` support if a structure
  parses, and never fetches an observation. The whole class of provider that
  publishes a readable catalogue over unreadable data is invisible to that
  probe. INEGI 404s on every data path and WB 403s, for the same reason.
- **`describe_flow` reports the size of a codelist, not the codes that carry
  data.** It reads the DSD, so BIS `WS_CBPOL` comes back as `REF_AREA: 239`
  when 49 areas have ever had an observation — a fivefold overstatement handed
  to an agent as a bare number, with nothing marking it as metadata. The
  content constraint that would narrow it is published and not read.
- **The cross-provider index answers a confident zero.** `provider="*"` matches
  names literally, with no stemming, synonyms or spelling normalisation, so
  `long-term interest rate` returns `total: 0` although OECD's `DF_FINMARK`
  carries `IRLT`; `labor force` returns 0 against 352 for `labour force`; and
  `broad money` returns 0. An empty answer reads as "nobody publishes this",
  and the note it carries — confirm against the provider named — names no
  provider. A stale index cannot return a stale number, which was the design
  claim, but it can and does return a false absence.
- **Search matches every localization, which crosses languages it should not.**
  The behaviour that finds ISTAT's `Coltivazioni` from `crops` also answers
  `find_dataflows("OECD", "fiscal")` with 161 flows led by tax datasets,
  because *fiscal* is French for tax. A query is matched against every language
  at once with nothing weighting the one it was written in.
- **Ranking prefers the derived series to the level it derives from.** Name
  length stands in for "no breakdowns", but short names are disproportionately
  ratios and deflators, which carry no qualifiers, while a headline level
  carries "at market prices". So ESTAT `gdp` leads with `GDP deflator`, and
  `inflation` leads with "Core inflation differential vis-à-vis EA" over
  "HICP - inflation rate". The position tiebreaker reads the *last* query word,
  which puts OECD's "Monthly unemployment rates" fourth for `unemployment rate`
  behind three education breakdowns, since "rate" falls at the end of the name.
- **Nothing tests that the index reaches an install.** The packaging test reads
  `catalogue.json.gz` from the source tree, so it passes on a machine where the
  file was built whether or not it is committed or packaged — the one failure
  it exists to catch. It should build a wheel and assert against that.
- **Observations are never cached, so every fetch pays full price.** That is
  deliberate (see Caching) but it means repeated identical queries re-download
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
- **The cross-provider index is a snapshot.** It is built by a script and
  shipped, so it goes stale between rebuilds: a flow retired yesterday is still
  listed, and one added yesterday is not. It is a routing hint and never an
  answer, so the cost is a wasted call rather than a wrong number, and four
  live tests sample it against the providers so drift fails the build. Rebuild
  with `uv run python -m scripts.catalogue`.
- **Singapore is not in the index.** It publishes no catalogue endpoint, only a
  search, so there is nothing to index; a cross-provider search says so rather
  than implying SingStat has nothing. Hong Kong is in it, folded in from the
  table already in `hkma.py`.
- **Search ranks on the name and nothing else.** A dataflow carries no
  popularity, no observation count and no flag saying which is the headline
  series, so the ordering reads the only signal there is: the shape of the
  name. It holds where a provider names a flow as a subject plus its
  breakdowns, which is most of them, and it is a heuristic either way.
- **Ranking does not apply to the adapters' own search.** Singapore delegates
  search to SingStat's endpoint and returns its relevance order; Hong Kong
  matches slugs alphabetically, having no titles to rank. Both come back well
  under the limit in practice, so neither has met the problem the ordering was
  for.
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
- **A cold fetch downloads the structure twice.** `sdmx1` resolves a dict key
  by fetching the DSD itself, and `_unit_labels` then fetches it again through
  `_dsd`, which does not know about the first: the same 497KB URL twice on ECB,
  3.5MB twice on an IMF vintage. Calling `describe_flow` first, which is the
  prescribed order, saves one of the two, and after the first fetch of a flow
  the process pays neither again. Passing a rendered key string rather than a
  dict would fix it.
- **`sdmx1` memoises structures on the Client class, not the instance.** So
  `MACRO_MCP_NO_CACHE=1` does not force a fresh structure read within one
  process, and neither does discarding the client: the dict outlives both. The
  live suite is weaker than it reads for that reason, and a before-and-after
  measurement taken in one process is worthless: the second half reads what
  the first downloaded.
- **The download is capped per series, not per response.** `lastNObservations`
  bounds each series the key matches, so a wildcard over 300 series still
  fetches `limit + 1` observations for every one of them. `limit` bounds what
  comes back; only the key bounds what is fetched.
- **`total` is a floor once the cap binds.** It used to be the length of the
  series, which was free only because the whole series had been downloaded.
  Now it counts what arrived, and a series that came back at the cap has older
  observations nobody counted. The `truncated` note says which of the two it
  is; there is no way to report the exact length without paying for it again.
- **Not every provider honours the cap, and one applied it wrongly.** It is
  sent to all of them. BIS, ECB, IMF, Bundesbank and OECD truncate at the
  source; UNSD and UNICEF returned the same bytes with the parameter as
  without, so they appear to ignore it. ILO does something worse: it drops
  whole series, returning 13 of 39 at the default `limit` and 39 at 2001. That
  shipped for a while and is the reason the first capped fetch of a provider is
  now checked against a `detail=nodata` count of the keys, and the verdict
  recorded against the cap it was measured at. A provider that refuses the
  parameter, or comes back short, is asked again without it and remembered for
  the life of the process.
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
  21KB of observations. It is paid once a week rather than once a call (see
  Caching) but on a cold process the download cap addresses the smaller part
  of the bill.
- **The cap does not reach the non-SDMX adapters.** Singapore and Hong Kong
  have no such parameter, so `limit` still bounds only their responses.
- **`limit` binds evenly, not by importance.** The budget is split max-min
  fair across the series in a response, so nothing is clipped while there is
  room and a short series hands its surplus to a long one. Once it does bind,
  though, every long series is cut to the same depth regardless of which one the
  question was about, and a response with more series than the budget can seat
  drops the excess, named under `dropped_series` but dropped all the same.
  Narrow `start`/`end`, or raise `limit`, when querying several series at once.
- **The first BIS fetch of a session pays for a failed parse.** BIS serves
  structure-specific data referencing a DSD `sdmx1` cannot resolve, so the
  payload is downloaded and parsed once before the generic form is tried. The
  provider is remembered after that and every later fetch goes generic-first,
  but the knowledge dies with the process, and `sdmx1` prints its parse stack
  and the failing element to stdout on the way, though the MCP SDK claims that
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
  provider whose structures are slow (ISTAT is 29s cold) pays for that
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

- **Asian national sources are mostly gated.** Headline macro for Asia is largely
  covered by the international providers, though less completely than this used to
  claim. Measured 2026-09-03: BIS policy rates (`WS_CBPOL`, 49 areas) carry JP, CN,
  IN, KR, HK, TH, MY, ID and PH, and not SG, TW, VN, PK or BD; residential property
  prices (`WS_SPP`, 61) add SG and still miss TW, VN, PK and BD. So four of the
  fourteen Asian economies once listed here are in neither, and Singapore has a
  property price and no policy rate. The IMF, World Bank and ILO are broader. What
  is missing is national detail, and there the constraint bites: e-Stat (Japan), ECOS (Korea), KOSIS and
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
  carry no local representation, so codes are reachable only through the
  concept each dimension identifies, and it writes monthly periods as
  `2024-M01`, which is rewritten to `2024-01` so the series joins against
  everything else.
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
