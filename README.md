# macro-mcp

MCP server for international macro statistics, company identity and FX rates.
Every source is free and keyless.

## Why

Most finance MCP servers wrap one API with one tool per endpoint. That does not
survive going international: there is no global EDGAR, no shared company key, and
each provider codes countries differently. This takes a different route.

- **One grammar, many providers.** SDMX is ISO 17369, and the BIS, ECB, IMF, OECD,
  Eurostat, World Bank, ILO and a dozen national offices all publish through it.
  One set of tools reaches all of them.
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
| `fetch_data` | Observations for a dimension key |
| `find_entity` | GLEIF search by legal name |
| `get_entity` | Look up one LEI |
| `entity_ownership` | Direct parent, ultimate parent, direct children |
| `fx_spot` | Daily ECB reference rate |
| `fx_period_rate` | Average or end-of-period rate |

## What it will not do for you

The server surfaces these; it does not silently fix them.

- Geo codelists mix aggregates and members (EU27 next to France). Summing both
  double-counts, and nothing errors.
- Nominal, PPP and constant-price series are not interchangeable.
- Fiscal years differ. India, Japan and Australia are not calendar-year.
- Seasonal adjustment differs: X-13 in the US, TRAMO/SEATS across much of Europe.
- Most providers publish revisions without point-in-time access, so history reads
  as-revised rather than as-known.
- Entity search matches broadly and may rank a subsidiary above its parent. Hits
  carry country and status; use `entity_ownership` to walk up the group.

## Known gaps

- **Asia is thin.** SDMX coverage is Europe, the Americas and Australia. Japan,
  China, India, Korea and Singapore each need their own adapter.
- **Endpoints drift.** `sdmx1` hardcodes base URLs that go stale as institutions
  move. `URL_FIXES` corrects ABS (the old host stopped resolving) and Lithuania
  (moved to an APEX path); `AGENCY` corrects INEGI, whose flows are filed under a
  different agency id. Re-verify these if a provider starts failing.
- **Genuinely down:** Bundesbank and DG COMP 404 on every path, and Uruguay serves
  a self-signed certificate. ISTAT returns intermittent 500s. See `QUIRKS`.
- **WB_WDI and StatCan** serve data but not dataflow metadata, so flow ids must be
  known in advance. `list_providers` flags this.
- **Filings** are out of scope. There is no free global equivalent until ESAP
  opens its API in July 2027.
