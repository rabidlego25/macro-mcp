"""The web proof of concept in web/: its logic, its ranking, and its providers.

Three layers, cheapest first. The core logic has its own node tests, run from
here so one `pytest` covers the repository. The page's search ranking is a
port of `sdmx_api._rank`, and a port drifts unless something compares the two,
so the same queries run through both over the shipped web index. And, opt-in
with MACRO_MCP_LIVE=1, each provider is loaded in headless Chrome to confirm a
chart actually draws, which is the one thing nothing short of a browser shows:
a provider can answer a server perfectly and still be unreadable to a page.
"""

import functools
import http.server
import json
import os
import pathlib
import shutil
import subprocess
import sys
import threading

import pytest

from macro_mcp import sdmx_api as api

ROOT = pathlib.Path(__file__).parent.parent
# scripts/ is run as `python -m scripts.x` from the checkout, not installed.
sys.path.insert(0, str(ROOT))
from scripts import web_catalogue  # noqa: E402

WEB = ROOT / "web"
NODE = shutil.which("node")
CHROME = next((c for c in (
    os.environ.get("CHROME"),
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    shutil.which("google-chrome"), shutil.which("google-chrome-stable"), shutil.which("chromium"),
) if c and os.path.exists(c)), None)

needs_node = pytest.mark.skipif(NODE is None, reason="node is not installed")


@needs_node
def test_core_logic():
    r = subprocess.run([NODE, "--test", str(WEB / "core.test.js")], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-2000:]


# Queries from the evals and the README, plus a few with ties and prefixes.
QUERIES = ["unemployment", "unemployment rate", "consumer price index", "gdp",
           "exchange rates", "policy rate", "national accounts", "labour force",
           "house prices", "balance of payments", "rate", "cpi"]


def python_top(q: str, flows: list, n: int = 10) -> list:
    hits = sorted((r, ident) for ident, name in flows
                  if (r := api._rank(q, ident, {0: name})) is not None)
    return [ident for _, ident in hits[:n]]


JS_TOP = """
const C = require(process.argv[1]);
const cat = require(process.argv[2]).providers;
const out = {};
for (const q of JSON.parse(process.argv[3])) {
  const cq = C.compileQuery(q, { synonyms: false });
  out[q] = {};
  for (const [p, flows] of Object.entries(cat)) {
    out[q][p] = flows.map(([id, name]) => [C.rank(cq, id, name), id]).filter(([r]) => r)
      .sort((a, b) => C.cmp(a[0], b[0]) || (a[1] < b[1] ? -1 : a[1] > b[1] ? 1 : 0))
      .slice(0, 10).map(([, id]) => id);
  }
}
console.log(JSON.stringify(out));
"""


@needs_node
def test_page_ranks_like_the_server():
    """With synonyms off the page must order results exactly as `_rank` does.

    Ties are broken by id on both sides, which is what Python's tuple sort
    does and what the page's stable sort does not guarantee on its own.
    """
    catalogue = json.loads((WEB / "catalogue.json").read_text())["providers"]
    r = subprocess.run([NODE, "-e", JS_TOP, str(WEB / "core.js"), str(WEB / "catalogue.json"),
                        json.dumps(QUERIES)], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr[-2000:]
    js = json.loads(r.stdout)
    for q in QUERIES:
        for p, flows in catalogue.items():
            assert js[q][p] == python_top(q, flows), (q, p)


def test_web_index_covers_the_page_providers():
    catalogue = json.loads((WEB / "catalogue.json").read_text())
    assert set(catalogue["providers"]) == set(web_catalogue.PROVIDERS)
    app = (WEB / "app.js").read_text()
    for p in web_catalogue.PROVIDERS:
        assert f"\n  {p}: {{" in app, f"{p} is indexed but app.js has no entry for it"


def test_new_datasets_are_dated_and_first_runs_mark_nothing():
    after = {"providers": {"BIS": [["A", "a"], ["B", "b"]], "NB": [["X", "x"]]}}
    assert web_catalogue.added({}, after, "2026-09-28", {}) == {}
    before = {"providers": {"BIS": [["A", "a"]]}}
    # NB was absent before, which means down rather than empty: nothing marked.
    assert web_catalogue.added(before, after, "2026-09-28", {}) == {"BIS/B": "2026-09-28"}
    old = {"BIS/Z": "2026-06-01", "BIS/B": "2026-09-20"}
    assert web_catalogue.added(before, after, "2026-09-28", old) == {"BIS/B": "2026-09-20"}


# One working selection per provider, as a link into the page.
LINKS = {
    "ESTAT": "",   # the page opens on Eurostat unemployment by default
    "ECB": "#ECB/EXR/M.USD%2BJPY.EUR.SP00.A",
    "BIS": "#BIS/WS_CBPOL/M.US%2BXM",
    "IMF_DATA": "#IMF_DATA/CPI/USA%2BGBR.CPI._T.IX.M",
    "ABS": "#ABS/CPI/1.10001.10.50.Q/yoy",
    "ILO": "#ILO/DF_CCF_XOXR_CUR_RT/USA%2BJPN.A..",
    "NB": "#NB/EXR/B.USD%2BEUR.NOK.SP",
    "SPC": "#SPC/DF_CPI/A.FJ..",
    "OECD": "#OECD/OECD.SDD.STES%3ADSD_STES%40DF_CLI(4.1)/USA%2BDEU.M.LI...AA...H",
}

live = pytest.mark.skipif(os.environ.get("MACRO_MCP_LIVE") != "1" or CHROME is None,
                          reason="set MACRO_MCP_LIVE=1, with Chrome installed, to load the page against live providers")


@pytest.fixture(scope="module")
def site():
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(WEB))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}/"
    server.shutdown()


def dump(url: str, profile: pathlib.Path, wait: float = 120) -> str:
    """The page's DOM once headless Chrome has let it settle.

    Read from the stream rather than waited for: Chrome writes the whole
    document and then, on this page, does not always exit, so waiting for the
    process would cost the full timeout on every provider.
    """
    proc = subprocess.Popen([CHROME, "--headless=new", "--disable-gpu", "--no-sandbox",
                             f"--user-data-dir={profile}", "--virtual-time-budget=30000",
                             "--dump-dom", url],
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    out: list[str] = []

    def read():
        for line in proc.stdout:
            out.append(line)
            if "</html>" in line:
                return

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    reader.join(wait)
    proc.kill()
    proc.wait()
    return "".join(out)


@live
@pytest.mark.parametrize("provider", list(LINKS))
def test_page_draws_a_chart(site, provider, tmp_path):
    dom = dump(site + LINKS[provider], tmp_path)
    if provider == "OECD" and 'class="chart"' not in dom:
        # OECD's bot check blocks browsers on some days. The page has to say so
        # rather than hang or break; that is what is tested when it does.
        assert "did not reach OECD" in dom or "bot check" in dom, dom[-2000:]
        pytest.skip("OECD is behind a bot check today; the page reported it")
    assert 'class="chart"' in dom, dom[-3000:]
