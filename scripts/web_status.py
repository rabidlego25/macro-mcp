"""Check that each provider the web page uses still answers a browser.

One known query per provider, asked the way the page asks it: the structure
request, then the data request, each with an Origin header, and the answer
must carry a cross-origin header or a browser would never see it. OECD shows
why this is not the same as the provider being up: it sits behind a bot check
that answers 403 with no such header, which a server-side client sees as an
error page and a browser sees as the network failing.

    uv run python -m scripts.web_status

Writes web/status.json, which the page reads to mark a provider slow or down.
Exits non-zero only if every provider failed, which says more about the
machine running it than about the providers.
"""

import datetime
import json
import pathlib
import sys
import time

import requests

OUT = pathlib.Path(__file__).parent.parent / "web" / "status.json"
ORIGIN = "https://rabidlego25.github.io"
CSV = "application/vnd.sdmx.data+csv;version=1.0.0;labels=both"
STRUCT = "application/vnd.sdmx.structure+xml;version=2.1"
SLOW = 10.0

# provider: (structure url, data url, data Accept)
CHECKS = {
    "ESTAT": (
        "https://ec.europa.eu/eurostat/api/dissemination/sdmx/2.1/datastructure/ESTAT/UNE_RT_M",
        "https://ec.europa.eu/eurostat/api/dissemination/sdmx/2.1/data/UNE_RT_M/M.SA.TOTAL.PC_ACT.T.DE"
        "?lastNObservations=2&format=SDMX-CSV", CSV),
    "OECD": (
        "https://sdmx.oecd.org/public/rest/dataflow/OECD.SDD.STES/DSD_STES@DF_CLI/latest?references=datastructure",
        "https://sdmx.oecd.org/public/rest/data/OECD.SDD.STES,DSD_STES@DF_CLI,/USA.M.LI...AA...H?lastNObservations=2",
        CSV),
    "ECB": (
        "https://data-api.ecb.europa.eu/service/dataflow/ECB/EXR/latest?references=datastructure",
        "https://data-api.ecb.europa.eu/service/data/EXR/M.USD.EUR.SP00.A?lastNObservations=2", "text/csv"),
    "BIS": (
        "https://stats.bis.org/api/v1/dataflow/BIS/WS_CBPOL/latest?references=datastructure",
        "https://stats.bis.org/api/v1/data/WS_CBPOL/M.US?lastNObservations=2", CSV),
    "IMF_DATA": (
        "https://api.imf.org/external/sdmx/2.1/dataflow/all/CPI/latest?references=datastructure",
        "https://api.imf.org/external/sdmx/2.1/data/IMF.STA,CPI/USA.CPI._T.IX.M?lastNObservations=2",
        "application/vnd.sdmx.structurespecificdata+xml;version=2.1"),
    "ABS": (
        "https://data.api.abs.gov.au/rest/dataflow/ABS/CPI/latest?references=datastructure",
        "https://data.api.abs.gov.au/rest/data/ABS,CPI/1.10001.10.50.Q?lastNObservations=2", CSV),
    "ILO": (
        "https://sdmx.ilo.org/rest/dataflow/ILO/DF_CCF_XOXR_CUR_RT/latest?references=datastructure",
        "https://sdmx.ilo.org/rest/data/ILO,DF_CCF_XOXR_CUR_RT/USA.A..?lastNObservations=2", CSV),
    "NB": (
        "https://data.norges-bank.no/api/dataflow/NB/EXR/latest?references=datastructure",
        "https://data.norges-bank.no/api/data/NB,EXR/B.USD.NOK.SP?lastNObservations=2", CSV),
    "SPC": (
        "https://stats-nsi-stable.pacificdata.org/rest/dataflow/SPC/DF_CPI/latest?references=datastructure",
        "https://stats-nsi-stable.pacificdata.org/rest/data/SPC,DF_CPI/A.FJ..?lastNObservations=2", CSV),
}


def ask(url: str, accept: str) -> tuple[float, str | None]:
    """Seconds taken, and what went wrong from a browser's side, if anything."""
    started = time.monotonic()
    try:
        r = requests.get(url, headers={"Accept": accept, "Origin": ORIGIN}, timeout=45)
    except requests.RequestException as e:
        return time.monotonic() - started, f"no answer ({type(e).__name__})"
    took = time.monotonic() - started
    if "challenges.cloudflare" in r.text or "Just a moment" in r.text:
        return took, "a bot check is blocking browsers"
    if not r.ok:
        return took, f"answered {r.status_code}"
    if not r.headers.get("Access-Control-Allow-Origin"):
        return took, "answered, but without a cross-origin header, so browsers cannot read it"
    if not r.text.strip():
        return took, "answered with nothing"
    return took, None


def check(provider: str) -> dict:
    structure, data, accept = CHECKS[provider]
    t1, err = ask(structure, STRUCT)
    if err:
        return {"state": "down", "note": f"structure request: {err}", "seconds": round(t1, 1)}
    t2, err = ask(data, accept)
    if err:
        return {"state": "down", "note": f"data request: {err}", "seconds": round(t1 + t2, 1)}
    total = t1 + t2
    if total > SLOW:
        return {"state": "slow", "note": f"answered in {total:.0f}s", "seconds": round(total, 1)}
    return {"state": "ok", "note": f"answered in {total:.1f}s", "seconds": round(total, 1)}


def main() -> int:
    results = {p: check(p) for p in CHECKS}
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    OUT.write_text(json.dumps({"checked": now, "providers": results}, indent=1) + "\n")
    for p, r in results.items():
        print(f"{p:<10} {r['state']:<5} {r['note']}", file=sys.stderr)
    return 1 if all(r["state"] == "down" for r in results.values()) else 0


if __name__ == "__main__":
    sys.exit(main())
