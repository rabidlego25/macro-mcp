"""The MCP surface: the twelve tools an agent is actually handed.

Everything under this file is covered — packing, the SDMX spine, GLEIF, the FX
conventions — and this layer executed no lines at all. It is not glue. What it
publishes is the contract: the names the instructions send an agent to, which
arguments it may leave out, what the defaults then are, and the docstrings that
say how to read a response. Every one of those can drift away from the code
beneath it without failing a single test elsewhere.

The tools are coroutines. There is no asyncio plugin here and one `asyncio.run`
per call does not need one.
"""

import asyncio
import json
import re
from importlib.metadata import version

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from conftest import GLEIF_ROUTES, TOYOTA, replay
from macro_mcp import entities, fx, sdmx_api, server, vintages

TOOLS = ["list_providers", "find_dataflows", "describe_flow", "search_codes",
         "fetch_data", "list_vintages", "compare_vintages", "find_entity",
         "get_entity", "entity_ownership", "fx_spot", "fx_period_rate"]

JPY = {"FREQ": "D", "CURRENCY": "JPY", "CURRENCY_DENOM": "EUR",
       "EXR_TYPE": "SP00", "EXR_SUFFIX": "A"}


def published() -> dict:
    return {t.name: t for t in asyncio.run(server.mcp.list_tools())}


def call(tool: str, /, **arguments) -> str:
    """The text an agent receives. These tools declare no output schema, so the
    whole response travels as one JSON string in the first content block."""
    result = asyncio.run(server.mcp.call_tool(tool, arguments))
    assert not result.is_error
    assert len(result.content) == 1
    return result.content[0].text


def payload(tool: str, /, **arguments) -> dict:
    return json.loads(call(tool, **arguments))


# --- what the agent is told --------------------------------------------------

def test_the_server_reports_the_installed_version_to_a_client():
    """It reported "" until a stdio probe showed it. A client displays this,
    and the answer to "which build is this" cannot be a second copy of the
    number in pyproject, so it is read from the installed metadata."""
    assert server.mcp.version == version("macro-mcp") != ""


def test_the_published_tools_are_the_twelve_and_no_others():
    """A tool added or renamed here changes what every agent sees, so the list
    is written out rather than counted."""
    assert list(published()) == TOOLS


def test_every_tool_the_instructions_send_an_agent_to_exists():
    """The instructions prescribe a discovery order by name. A tool renamed
    without touching the prose leaves an agent following a route to nothing,
    and nothing else in this suite reads the prose."""
    named = set(re.findall(r"[a-z]+(?:_[a-z]+)+", server.INSTRUCTIONS))
    assert named <= set(TOOLS)
    assert {"list_providers", "find_dataflows", "describe_flow", "search_codes",
            "fetch_data"} <= named, "the prescribed order"


def test_the_description_an_agent_reads_is_the_function_s_own_docstring():
    """The description is the only thing an agent has before calling, and there
    is no second copy of it to keep in step: editing the docstring is how the
    contract changes. A tool that lost it would still work and still mislead."""
    for name, tool in published().items():
        assert tool.description, name
        assert tool.description == getattr(server, name).__doc__, name


def test_the_fetch_docstring_says_that_a_total_can_be_a_floor():
    """Since the download is capped, `total` counts what arrived rather than
    the series. An agent reading it as a length reports a history that stops
    where the budget did, and this sentence is the only warning it gets."""
    described = published()["fetch_data"].description
    assert '"total" counts what the provider sent' in described
    assert "a floor" in described and "Narrow start/end" in described


def test_the_arguments_an_agent_may_leave_out_are_the_optional_ones():
    """Requiring a search term would force a guess; making a provider optional
    would let one be omitted silently."""
    assert {n: t.input_schema.get("required", []) for n, t in published().items()} == {
        "list_providers": [],
        "find_dataflows": ["provider"],
        "describe_flow": ["provider", "flow"],
        "search_codes": ["provider", "flow", "dimension"],
        "fetch_data": ["provider", "flow", "key"],
        "list_vintages": ["provider", "flow"],
        "compare_vintages": ["provider", "flow", "key"],
        "find_entity": ["name"],
        "get_entity": ["lei"],
        "entity_ownership": ["lei"],
        "fx_spot": ["base", "quote"],
        # A conversion window is the argument; there is no sensible default
        # period to average over.
        "fx_period_rate": ["currency", "start", "end"],
    }


def test_the_defaults_an_omitted_argument_takes_are_the_published_ones():
    """These are what an agent budgets against: it asks for 500 observations by
    not asking. A default that moves changes response sizes everywhere."""
    assert {n: {k: v["default"] for k, v in t.input_schema["properties"].items()
                if "default" in v}
            for n, t in published().items()} == {
        "list_providers": {},
        "find_dataflows": {"search": "", "limit": 40},
        "describe_flow": {},
        "search_codes": {"query": "", "limit": 30},
        "fetch_data": {"start": "", "end": "", "limit": 500},
        "list_vintages": {},
        "compare_vintages": {"start": "", "end": "", "limit": 5},
        "find_entity": {"country": "", "limit": 10},
        "get_entity": {},
        "entity_ownership": {},
        "fx_spot": {"date": ""},
        "fx_period_rate": {"convention": "average", "freq": "M", "limit": 500},
    }


def test_a_dimension_key_is_declared_as_an_object_and_not_a_string():
    """`key` is the one structured argument. Declared as a string it would
    arrive as "{'FREQ': 'M'}" and be read as a dimension id."""
    for name in ("fetch_data", "compare_vintages"):
        assert published()[name].input_schema["properties"]["key"] == {
            "additionalProperties": True, "title": "Key", "type": "object"}


# --- what an omitted argument becomes ----------------------------------------

class Recorder:
    def __init__(self):
        self.args = None

    def __call__(self, *args, **kwargs):
        self.args = (args, kwargs)
        return {}


ABSENT = [
    ("find_dataflows", sdmx_api, "dataflows", {"provider": "ECB"},
     ("ECB", None, 40)),
    ("fetch_data", sdmx_api, "fetch", {"provider": "ECB", "flow": "EXR", "key": JPY},
     ("ECB", "EXR", JPY, None, None, 500)),
    ("compare_vintages", vintages, "compare",
     {"provider": "IMF_DATA", "flow": "WEO", "key": {}},
     ("IMF_DATA", "WEO", {}, None, None, 5)),
    ("find_entity", entities, "search", {"name": "Toyota"}, ("Toyota", None, 10)),
    ("fx_spot", fx, "spot", {"base": "EUR", "quote": "USD"}, ("EUR", "USD", None)),
]


@pytest.mark.parametrize("tool, module, fn, arguments, expected", ABSENT,
                         ids=[row[0] for row in ABSENT])
def test_an_argument_left_out_arrives_as_absent_and_not_as_empty_text(
        monkeypatch, tool, module, fn, arguments, expected):
    """The schema spells "not given" as "", because MCP arguments are typed and
    an optional string cannot be null. Forwarded literally, an omitted date
    becomes `startPeriod=` in a URL and an omitted country a filter matching no
    jurisdiction — both of which return a plausible wrong answer."""
    recorder = Recorder()
    monkeypatch.setattr(module, fn, recorder)
    call(tool, **arguments)
    assert recorder.args == (expected, {})


def test_an_empty_search_term_is_forwarded_because_it_means_every_code(
        monkeypatch):
    """The opposite case, and the reason this is not one blanket rule: a code
    search with no term lists the dimension rather than declining to look."""
    recorder = Recorder()
    monkeypatch.setattr(sdmx_api, "search_codes", recorder)
    call("search_codes", provider="ECB", flow="EXR", dimension="CURRENCY")
    assert recorder.args == (("ECB", "EXR", "CURRENCY", "", 30), {})


def test_a_date_that_was_given_reaches_the_layer_below_unchanged(monkeypatch):
    recorder = Recorder()
    monkeypatch.setattr(sdmx_api, "fetch", recorder)
    call("fetch_data", provider="ECB", flow="EXR", key=JPY,
         start="2026-08-01", end="2026-08-28", limit=3)
    assert recorder.args == (("ECB", "EXR", JPY, "2026-08-01", "2026-08-28", 3), {})


# --- through the tool to the provider and back -------------------------------

def test_a_fetch_through_the_server_returns_the_packed_shape(spine):
    """The same response test_spine asserts on, reached the way an agent
    reaches it: through argument validation, a worker thread and JSON."""
    got = payload("fetch_data", provider="ECB", flow="EXR", key=JPY, limit=3)
    assert got["key"] == JPY
    assert got["units"]["UNIT"] == "Japanese yen"
    assert got["series"] == [{"key": {}, "observations": [
        ["2026-08-26", 185.62], ["2026-08-27", 185.61], ["2026-08-28", 185.92]]}]
    assert "most recent 3 of at least 4" in got["truncated"]


def test_the_text_an_agent_parses_is_json_a_strict_parser_accepts(spine):
    """An empty observation is a float NaN all the way up to packing, and bare
    NaN is not JSON. The tool layer serialises, so this is where it shows."""
    text = call("fetch_data", provider="ECB", flow="EXR", key=JPY, limit=3)
    assert "NaN" not in text
    json.loads(text, parse_constant=lambda c: pytest.fail(f"non-JSON token {c}"))


def test_omitting_the_dates_asks_the_provider_for_no_period_at_all(spine):
    """The end of the path the wiring test stubs out: "" must not survive as
    far as the query string."""
    call("fetch_data", provider="ECB", flow="EXR", key=JPY, limit=3)
    data = next(u for u in spine.urls if "/data/" in u)
    assert "Period" not in data
    assert data.endswith("D.JPY.EUR.SP00.A?lastNObservations=4")


def test_discovery_runs_end_to_end_through_the_tools_in_the_prescribed_order(spine):
    """list_providers, find_dataflows, describe_flow, search_codes, fetch_data:
    the route the instructions give, with each step's output feeding the next."""
    assert "ECB" in [p["id"] for p in payload("list_providers")["europe"]]

    flows = payload("find_dataflows", provider="ECB", search="exchange")
    assert flows["shown"][0]["id"] == "EXR"

    dimensions = payload("describe_flow", provider="ECB", flow="EXR")["dimensions"]
    assert [d["id"] for d in dimensions][:2] == ["FREQ", "CURRENCY"]

    codes = payload("search_codes", provider="ECB", flow="EXR",
                    dimension="CURRENCY", query="yen")
    assert codes["shown"] == [{"id": "JPY", "name": "Japanese yen"}]

    got = payload("fetch_data", provider="ECB", flow="EXR", key=JPY, limit=3)
    assert got["range"] == ["2026-08-26", "2026-08-28"]


def test_a_provider_without_vintages_says_so_rather_than_listing_none(spine):
    """Only IMF publishes point-in-time flows. An empty list would read as "no
    revisions found", which is the opposite of "this provider cannot tell you"
    — and the agent is deciding whether to claim what was known at a date."""
    got = payload("list_vintages", provider="ECB", flow="EXR")
    assert got["vintages"] == []
    assert "publishes no vintages of EXR" in got["note"]
    assert "as-revised rather than as-known" in got["note"]


def test_comparing_vintages_that_do_not_exist_costs_no_observations(spine):
    """It returns the same note, and returns it before fetching anything: a
    comparison of one flow against itself would report no revision and be
    indistinguishable from a comparison that found none."""
    got = payload("compare_vintages", provider="ECB", flow="EXR", key=JPY)
    assert got["vintages"] == [] and "revisions" not in got
    assert not [u for u in spine.urls if "/data/" in u]


def test_a_spot_rate_is_read_off_the_same_recorded_fixing(spine):
    """EXR is where the FX tools get their numbers, so the recorded exchange
    rates serve them too: one fixing, quoted the way fx_spot promises."""
    got = payload("fx_spot", base="EUR", quote="JPY", date="2026-08-28")
    assert got["rate"] == 185.92 and got["date"] == "2026-08-28"
    assert got["derived"] is False
    assert "note" not in got and "note_date" not in got


def test_an_inverted_pair_is_still_the_ecb_rate_and_not_a_cross(spine):
    """JPY/EUR is EUR/JPY upside down, taken from the same publication. Only a
    pair with no euro in it is derived, and this one is not."""
    got = payload("fx_spot", base="JPY", quote="EUR", date="2026-08-28")
    assert got["rate"] == 1 / 185.92
    assert got["derived"] is False


def test_a_period_rate_carries_the_window_it_was_asked_for_into_the_url(spine):
    """Unlike a fetch, both dates are required here — a conversion window is
    the argument — so they must arrive as periods rather than as a cap."""
    got = payload("fx_period_rate", currency="JPY", start="2026-08-01",
                  end="2026-08-28", freq="D", limit=3)
    assert got["quoted"] == "JPY per EUR" and got["convention"] == "average"
    assert got["range"] == ["2026-08-26", "2026-08-28"]

    data = next(u for u in spine.urls if "/data/" in u)
    assert "D.JPY.EUR.SP00.A?startPeriod=2026-08-01&endPeriod=2026-08-28" in data


def test_an_entity_lookup_reaches_gleif_through_its_own_tools(monkeypatch):
    """The other half of the surface: three tools that do not touch SDMX."""
    replay(monkeypatch, GLEIF_ROUTES)

    assert payload("find_entity", name="Toyota Motor",
                   country="JP")["hits"][0]["lei"] == TOYOTA
    assert payload("get_entity", lei=TOYOTA)["name"] == "トヨタ自動車株式会社"

    owners = payload("entity_ownership", lei=TOYOTA)
    assert owners["direct_parent"] is None
    assert owners["direct_children"][0]["name"]


def test_a_native_script_name_survives_the_json_serialisation(monkeypatch):
    """Escaped or transliterated, the name stops matching the register it came
    from. It is returned as the characters GLEIF sent."""
    replay(monkeypatch, GLEIF_ROUTES)
    assert "トヨタ自動車株式会社" in call("get_entity", lei=TOYOTA)


# --- what a failure looks like -----------------------------------------------

def test_an_unknown_provider_fails_with_the_list_of_known_ones():
    """An agent that guessed a provider id can recover from this; a bare
    KeyError or an empty result gives it nothing to correct."""
    with pytest.raises(ToolError) as raised:
        call("find_dataflows", provider="NOPE")
    assert "ECB" in str(raised.value) and "IMF_DATA" in str(raised.value)


def test_a_currency_that_is_not_a_currency_is_rejected_before_any_request():
    """fx validates its own arguments, which the schema cannot: "US" and
    "DOLLAR" are both strings."""
    with pytest.raises(ToolError, match="three-letter currency code"):
        call("fx_spot", base="DOLLAR", quote="EUR")


def test_an_argument_of_the_wrong_type_is_refused_rather_than_coerced():
    """`key` is validated against the published schema before the tool runs, so
    a string never reaches the SDMX layer to be misread as a dimension."""
    with pytest.raises(ToolError):
        call("fetch_data", provider="ECB", flow="EXR", key="FREQ.D")
