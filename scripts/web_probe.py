"""Which other providers could the web page use?

The page needs three things of a provider, all from a browser: a cross-origin
header on every answer, a structure request that returns in seconds, and data
in SDMX-CSV or structure-specific XML. This asks each indexed provider the
page does not yet use, with its first catalogued dataflow, and reports.

    uv run python -m scripts.web_probe

Prints a table. A provider that passes still needs an entry in web/app.js,
since each one takes its flow reference in its own form.
"""

import gzip
import json
import re
import sys
import time
import xml.etree.ElementTree as ET

import requests

from macro_mcp import sdmx_api as api
from scripts.web_catalogue import PROVIDERS as USED

ORIGIN = "https://rabidlego25.github.io"
STRUCT = "application/vnd.sdmx.structure+xml;version=2.1"
CSV = "application/vnd.sdmx.data+csv;version=1.0.0"
TIMEOUT = 30


def get(url, accept):
    started = time.monotonic()
    r = requests.get(url, headers={"Accept": accept, "Origin": ORIGIN}, timeout=TIMEOUT)
    return r, time.monotonic() - started


def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def probe(provider: str, flow: str) -> dict:
    from sdmx.source import sources
    base = sources[provider].url.rstrip("/")
    m = re.fullmatch(r"(?:([^:]+):)?([^()]+)(?:\((.+)\))?", flow)
    agency = m[1] or api.AGENCY.get(provider) or sources[provider].id
    fid, version = m[2], m[3] or "latest"
    out = {"provider": provider, "flow": flow}

    try:
        r, took = get(f"{base}/dataflow/{agency}/{fid}/{version}?references=datastructure", STRUCT)
    except requests.RequestException as e:
        return {**out, "verdict": f"structure: no answer ({type(e).__name__})"}
    out["structure"] = f"{r.status_code} in {took:.1f}s"
    if not r.ok:
        return {**out, "verdict": f"structure answered {r.status_code}"}
    if not r.headers.get("Access-Control-Allow-Origin"):
        return {**out, "verdict": "no cross-origin header"}
    try:
        root = ET.fromstring(r.content)
    except ET.ParseError:
        return {**out, "verdict": "structure is not XML"}
    dims = sorted(((int(e.get("position") or 0), e.get("id")) for e in root.iter()
                   if local(e.tag) == "Dimension" and e.get("id")))
    if not dims:
        return {**out, "verdict": "structure has no dimensions"}

    # Pick the first available code in each dimension, so the data request is
    # one series rather than the whole flow.
    key = "all"
    try:
        r2, _ = get(f"{base}/availableconstraint/{agency},{fid}/all/all/all", STRUCT)
        if r2.ok:
            first = {}
            for kv in ET.fromstring(r2.content).iter():
                if local(kv.tag) == "KeyValue":
                    vals = [v.text for v in kv if local(v.tag) == "Value" and v.text]
                    if vals:
                        first[kv.get("id")] = vals[0].strip()
            if first:
                key = ".".join(first.get(d, "") for _, d in dims)
                out["availability"] = "yes"
    except (requests.RequestException, ET.ParseError):
        pass
    out.setdefault("availability", "no")

    try:
        r3, took = get(f"{base}/data/{agency},{fid}/{key}?lastNObservations=1", CSV)
    except requests.RequestException as e:
        return {**out, "verdict": f"data: no answer ({type(e).__name__})"}
    out["data"] = f"{r3.status_code} in {took:.1f}s, {r3.headers.get('Content-Type', '?').split(';')[0]}"
    if not r3.ok:
        return {**out, "verdict": f"data answered {r3.status_code}"}
    if not r3.headers.get("Access-Control-Allow-Origin"):
        return {**out, "verdict": "data has no cross-origin header"}
    ctype = r3.headers.get("Content-Type", "")
    if "csv" not in ctype and "structurespecific" not in ctype and not r3.text.lstrip().startswith("DATAFLOW"):
        return {**out, "verdict": f"data came back as {ctype.split(';')[0]}"}
    if took > 15:
        return {**out, "verdict": f"works, but data took {took:.0f}s"}
    return {**out, "verdict": "usable"}


def main() -> None:
    catalogue = json.loads(gzip.decompress(api.CATALOGUE.read_bytes()))["providers"]
    for provider, flows in catalogue.items():
        if provider in USED or provider in api.NATIVE or not flows:
            continue
        r = probe(provider, flows[0][0])
        print(f"{r['provider']:<13} {r['verdict']:<45} structure {r.get('structure', '-'):<14} "
              f"availability {r.get('availability', '-'):<4} data {r.get('data', '-')}", flush=True)


if __name__ == "__main__":
    main()
