"""Cache policy and the capability table.

Both replace something that was silently wrong: sdmx1's `source.supports` is a
static declaration that disagrees with the live services, and in-process
memoisation threw away metadata that costs two minutes to rebuild.
"""

import pytest
from requests_cache.policy.expiration import get_url_expiration

from macro_mcp import cache
from macro_mcp import sdmx_api as api

DATA_URLS = [
    "https://api.statistiken.bundesbank.de/rest/data/BBSIS/D.I.ZAR",
    "https://data-api.ecb.europa.eu/service/data/EXR/M.JPY.EUR.SP00.A",
    "https://stats.bis.org/api/v2/data/dataflow/BIS/WS_CBPOL/1.0/M.JP",
    "http://data.un.org/WS/rest/data/DF_UNData_UNFCC/A.AUS",
    "https://tablebuilder.singstat.gov.sg/api/table/tabledata/M213801",
]

METADATA_URLS = [
    "https://api.statistiken.bundesbank.de/rest/metadata/dataflow/BBK",
    "https://api.statistiken.bundesbank.de/rest/metadata/codelist/BBK/CL_X",
    "https://sdw-wsrest.ecb.europa.eu/service/dataflow/ECB",
    "https://sdmx.ilo.org/rest/dataflow",
    "https://sdmx.oecd.org/public/rest/dataflow/ESTAT/SEEA_AEA_A/1.4",
    "https://tablebuilder.singstat.gov.sg/api/table/resourceid?keyword=cpi",
]

# Reachable hosts with no declared policy: adapters not yet written, and the
# non-SDMX services.
UNDECLARED_URLS = [
    "https://api.hkma.gov.hk/public/market-data-and-statistics/daily/x",
    "https://api.data.gov.my/data-catalogue?id=cpi_headline",
    "https://api.gleif.org/api/v1/lei-records?filter=x",
    "https://api.frankfurter.app/latest?from=EUR",
]


@pytest.mark.parametrize("url", DATA_URLS)
def test_observations_are_never_served_from_cache(url):
    """Stale metadata is an annoyance; a stale exchange rate is a wrong answer."""
    assert get_url_expiration(url, cache.EXPIRY) == 0


@pytest.mark.parametrize("url", METADATA_URLS)
def test_metadata_is_cached_for_the_full_ttl(url):
    assert get_url_expiration(url, cache.EXPIRY) == cache.TTL


def test_data_patterns_win_over_structure_patterns():
    """BIS puts /data/dataflow/ in its data URLs. The first matching pattern
    wins, so the data entries have to be declared first; reordering the dict
    would start caching BIS observations for a week."""
    url = "https://stats.bis.org/api/v2/data/dataflow/BIS/WS_CBPOL/1.0/M.JP"
    assert list(cache.EXPIRY).index("*/data/*") < list(cache.EXPIRY).index("*/dataflow*")
    assert get_url_expiration(url, cache.EXPIRY) == 0


def test_bundesbank_metadata_is_not_mistaken_for_data():
    """'metadata/dataflow' contains the substring 'data' but not '/data/'."""
    url = "https://api.statistiken.bundesbank.de/rest/metadata/dataflow/BBK"
    assert get_url_expiration(url, cache.EXPIRY) == cache.TTL


@pytest.mark.parametrize("url", UNDECLARED_URLS)
def test_undeclared_paths_are_not_cached(url):
    """The policy denies by default. Listing data paths instead failed open:
    SINGSTAT's /tabledata/ was not on that list and would have served week-old
    figures. Forgetting a path now costs a round trip, not correctness."""
    assert get_url_expiration(url, cache.EXPIRY) == 0


def test_the_catch_all_denies_rather_than_permits():
    assert cache.EXPIRY["*"] == 0


def test_cache_lives_under_the_xdg_cache_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    assert cache.path() == tmp_path / "macro-mcp" / "http"


@pytest.mark.parametrize("bypass,disabled", [("1", True), ("0", False)])
def test_cache_can_be_bypassed(monkeypatch, tmp_path, bypass, disabled):
    """sdmx.Session always carries the caching mixin, so bypass shows up as
    settings.disabled rather than as a missing attribute."""
    monkeypatch.setenv("MACRO_MCP_NO_CACHE", bypass)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    cache.session.cache_clear()
    try:
        s = cache.session()
        assert s.settings.disabled is disabled
        if not disabled:
            assert s.settings.urls_expire_after == cache.EXPIRY
    finally:
        cache.session.cache_clear()


@pytest.mark.parametrize("bypass", ["1", "0"])
def test_the_session_identifies_itself(monkeypatch, tmp_path, bypass):
    """SINGSTAT answers the default python-requests agent with a 403. That was
    invisible until it was wired in, because the survey script that found the
    endpoint sent its own header."""
    monkeypatch.setenv("MACRO_MCP_NO_CACHE", bypass)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    cache.session.cache_clear()
    try:
        ua = cache.session().headers["User-Agent"]
        assert ua == cache.USER_AGENT and "macro-mcp" in ua
        assert "python-requests" not in ua
    finally:
        cache.session.cache_clear()


def test_capability_comes_from_the_probe_not_sdmx1s_declaration():
    """sdmx1 advertises metadata for BBK, whose every standard path 404s. The
    adapter is what makes it true, and only a probe can see that."""
    assert api._supports("BBK", "dataflow")
    assert api._supports("BBK", "datastructure")
    assert not api._supports("WB_WDI", "dataflow")
    assert not api._supports("StatCan", "dataflow")


def test_partial_support_is_not_read_as_full_support():
    """Tuples, not strings: `'datastructure' in 'dataflow'` is False by luck,
    but `'flow' in 'dataflow'` would be True."""
    for provider, got in api.SUPPORTS.items():
        assert isinstance(got, tuple), f"{provider} is {type(got).__name__}"
        assert set(got) <= set(api.DEFAULT_SUPPORT)


def test_unprobed_providers_are_assumed_capable():
    """So adding a provider to GROUPS does not require a probe run first."""
    assert api._supports("NOT_PROBED_YET", "dataflow")


def test_every_grouped_provider_was_probed():
    grouped = {p for ps in api.GROUPS.values() for p in ps}
    assert grouped == set(api.SUPPORTS), grouped ^ set(api.SUPPORTS)


def test_providers_without_metadata_are_flagged_to_the_agent():
    entries = {e["id"]: e for group in api.providers().values() for e in group}
    assert "note" in entries["WB_WDI"]
    assert "note" not in entries["BIS"]


def test_a_structure_with_no_dimensions_is_an_error_not_an_answer(monkeypatch):
    """IMF used to land here: a DSD that parsed cleanly and was empty, so
    describe_flow reported a flow with no dimensions and no error. An
    unqueryable structure has to say so rather than defer the failure to
    fetch_data."""
    class Empty:
        dimensions = type("D", (), {"components": []})()

    monkeypatch.setattr(api, "_dsd", lambda p, f: Empty())
    assert "error" in api.describe_flow("BIS", "WS_CBPOL")
