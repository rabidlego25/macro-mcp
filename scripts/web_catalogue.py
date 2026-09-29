"""Cut the shipped index down to what the web proof of concept can query.

The page in web/ talks to providers straight from the browser, so it can only
list the ones that answer a browser: CSV or parseable XML, a cross-origin
header, and a structure request that returns in seconds rather than a minute.
`scripts.web_probe` checks the providers not listed here.

Only the English name is kept. The page searches one language and the other
localizations would double the download.

Also records which datasets are new since the last cut, in web/changes.json,
so the page can mark them. A dataset is new on the day it first appears and
stays listed for 60 days; the page shows the last fortnight of them.

    uv run python -m scripts.web_catalogue

Writes web/catalogue.json and web/changes.json.
"""

import datetime
import gzip
import json
import pathlib

from macro_mcp import sdmx_api as api

PROVIDERS = ["BIS", "ECB", "OECD", "ESTAT", "ABS", "IMF_DATA", "ILO", "NB", "SPC"]
WEB = pathlib.Path(__file__).parent.parent / "web"
OUT = WEB / "catalogue.json"
CHANGES = WEB / "changes.json"
KEEP_DAYS = 60


def load(path: pathlib.Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def added(before: dict, after: dict, today: str, log: dict) -> dict:
    """Datasets in `after` and not `before`, merged into `log` and aged out.

    A first run has nothing to compare against and marks nothing, rather than
    calling all 11,000 datasets new.
    """
    if before:
        for p, flows in after["providers"].items():
            old = {f[0] for f in before.get("providers", {}).get(p, [])}
            # A provider missing entirely last time was down, not empty.
            if not old:
                continue
            for ident, _ in flows:
                if ident not in old:
                    log.setdefault(f"{p}/{ident}", today)
    cutoff = (datetime.date.fromisoformat(today) - datetime.timedelta(days=KEEP_DAYS)).isoformat()
    return {k: d for k, d in sorted(log.items()) if d >= cutoff}


def main():
    built = json.loads(gzip.decompress(api.CATALOGUE.read_bytes()))
    out = {"built": built["built"],
           "providers": {p: [[ident, names[0] if names else ident]
                             for ident, *names in built["providers"].get(p, [])]
                         for p in PROVIDERS}}
    before = load(OUT)
    today = datetime.date.today().isoformat()
    log = added(before, out, today, load(CHANGES).get("added", {}))

    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")))
    CHANGES.write_text(json.dumps({"added": log}, indent=0, separators=(",", ":")) + "\n")
    print(OUT, OUT.stat().st_size, "bytes",
          sum(len(v) for v in out["providers"].values()), "flows;",
          sum(1 for d in log.values() if d == today), "new today")


if __name__ == "__main__":
    main()
