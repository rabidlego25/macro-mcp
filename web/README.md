# Open Macro Explorer

A proof of concept: the search and fetch half of macro-mcp as one static page,
with no server and no Python. The browser searches a snapshot of the provider
catalogues and asks each provider for data directly.

    cd web && python3 -m http.server 8765
    open http://localhost:8765

It has to be served over HTTP; opening `index.html` as a file stops the
catalogue from loading. Any static host works. `.github/workflows/pages.yml`
publishes it to GitHub Pages.

## What it does

- **Search** 12,500 datasets from nine providers in the browser, ranked the
  way `sdmx_api._rank` ranks them (`tests/test_web.py` holds the two to the
  same order), with a few synonyms on top: labor/labour, CPI, GDP, inflation.
  IMF's monthly snapshots are folded under the dataset they copy.
- **Pick codes by name.** Each dimension's codelist is fetched on its own and
  kept in the browser for a week, so `PC_ACT` reads "Percentage of population
  in the labour force".
- **See what exists.** Where the provider has an availability endpoint (BIS,
  OECD, IMF, ABS, Norges Bank, SPC), codes that cannot occur with the other
  choices are marked "no data", and the page says how many series match
  before anything is fetched.
- **Compare across scales.** View as level, indexed to 100 at the start, or
  percent change on a year earlier, with the units the provider sent.
- **Take it elsewhere.** Download CSV, copy a link that restores the dataset,
  selection and view, or copy the same query as a `fetch_data` call to the
  MCP server.

Links take the form `#PROVIDER/ID/KEY/VIEW`, for example
`#BIS/WS_CBPOL/M.US+XM+GB+JP/yoy`.

## Providers

Eurostat, OECD, ECB, BIS, IMF, ABS, ILO, Norges Bank and the Pacific
Community: the ones that answer a browser (a cross-origin header), return
SDMX-CSV or structure-specific XML, and describe a dataset in seconds.
`uv run python -m scripts.web_probe` checks the rest of the indexed providers
against those conditions.

OECD sits behind a Cloudflare bot check that some days blocks browsers
outright. The page says so rather than hanging, and the daily health check
marks it.

## Daily refresh

`.github/workflows/refresh.yml` runs each morning:

1. `scripts.catalogue` rebuilds the full index. A provider that is down, or
   returns under 80% of its previous flows, keeps yesterday's entries, and a
   rebuild that finds nothing new leaves the file unchanged.
2. `scripts.web_catalogue` cuts it down for the page and records datasets that
   are new, which the page marks for a fortnight.
3. The index is committed if it changed, and the page is republished with a
   fresh `scripts.web_status` health check, shown as a dot on any provider
   that is slow or down.
4. The live tests run: `test_live.py` for the server, and `test_web.py`, which
   loads one chart per provider in headless Chrome.

## Files

- `index.html`: markup and styles.
- `core.js`: search, CSV, periods, views. No DOM, so `core.test.js` runs it
  under node.
- `app.js`: providers, network, pickers, chart.
- `catalogue.json`, `changes.json`: written by `scripts.web_catalogue`.
- `status.json`: written by `scripts.web_status` at deploy time; not committed.

## What it still leaves out, against the MCP server

- The provider workarounds in `sdmx_api.py`: no check that a capped request
  kept every series, no fallback formats.
- Bundesbank, Singapore, Hong Kong and the providers the probe rejects.
- Vintages, entities and FX tools.
