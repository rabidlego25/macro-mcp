"""MCP server over SDMX statistical providers, GLEIF entities and ECB FX rates.

Discovery is progressive: providers -> dataflows -> describe_flow -> search_codes
-> fetch. Metadata is never returned whole, since a single codelist can run to
hundreds of entries.
"""

from mcp.server import MCPServer

from . import entities, fx, sdmx_api

INSTRUCTIONS = """Free international macro, entity and FX data. No API keys.

Work through discovery in order: list_providers, find_dataflows, describe_flow,
search_codes, then fetch_data. Do not guess dimension codes; resolve them with
search_codes, including country codes, which differ per provider.

Cross-country comparisons break in predictable ways. Check each before reporting:
- Aggregates and members coexist in the same geo codelist (EU27 alongside France).
  Summing both double-counts.
- Convert with the right rate: period average for flows, end-of-period for stocks.
- Nominal, PPP and constant-price series are not interchangeable.
- Fiscal years differ (India, Japan, Australia are not calendar-year).
- Seasonal adjustment differs (X-13 in the US, TRAMO/SEATS across much of Europe).
- Most providers publish revisions without point-in-time access, so historical
  values are as-revised, not as-known. Say so when it affects the conclusion.

Search in English regardless of the provider's language. Names are matched across
every localization the provider publishes and returned in English where it exists,
so "crops" finds an Italian dataflow named Coltivazioni.

Some providers serve data but not metadata; list_providers reports which. For
those, the dataflow id has to be known up front.

Resolve companies by LEI before joining anything across jurisdictions.
"""

mcp = MCPServer("macro-mcp", instructions=INSTRUCTIONS)


@mcp.tool()
def list_providers() -> dict:
    """Statistical providers by region, with known per-provider quirks."""
    return sdmx_api.providers()


@mcp.tool()
def find_dataflows(provider: str, search: str = "", limit: int = 40) -> dict:
    """Search a provider's dataflows by id or name."""
    return sdmx_api.dataflows(provider, search or None, limit)


@mcp.tool()
def describe_flow(provider: str, flow: str) -> dict:
    """Dimensions of a dataflow with code counts and a short sample."""
    return sdmx_api.describe_flow(provider, flow)


@mcp.tool()
def search_codes(provider: str, flow: str, dimension: str, query: str = "",
                 limit: int = 30) -> dict:
    """Find valid codes for one dimension. Use this to map a country name onto a
    provider's geo codelist."""
    return sdmx_api.search_codes(provider, flow, dimension, query, limit)


@mcp.tool()
def fetch_data(provider: str, flow: str, key: dict, start: str = "", end: str = "",
               limit: int = 500) -> dict:
    """Fetch observations. key maps dimension ids to codes, e.g.
    {"FREQ": "M", "CURRENCY": "USD"}."""
    return sdmx_api.fetch(provider, flow, key, start or None, end or None, limit)


@mcp.tool()
def find_entity(name: str, country: str = "", limit: int = 10) -> dict:
    """Search GLEIF by legal name. Verify country and status on every hit."""
    return entities.search(name, country or None, limit)


@mcp.tool()
def get_entity(lei: str) -> dict:
    """Look up one LEI."""
    return entities.get(lei)


@mcp.tool()
def entity_ownership(lei: str) -> dict:
    """Direct parent, ultimate parent and direct children for an LEI."""
    return entities.ownership(lei)


@mcp.tool()
def fx_spot(base: str, quote: str, date: str = "") -> dict:
    """Daily ECB reference rate. Omit date for the latest."""
    return fx.spot(base, quote, date or None)


@mcp.tool()
def fx_period_rate(currency: str, start: str, end: str, convention: str = "average",
                   freq: str = "M") -> dict:
    """EUR rates by convention: "average" to convert flows, "end_of_period" for
    stocks. Dates are ISO, e.g. 2024-01."""
    return fx.period_rate(currency, start, end, convention, freq)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
