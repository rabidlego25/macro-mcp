"""Rebuild hkma.SECTIONS from the published documentation.

HKMA serves no catalogue endpoint, so the dataset list in `hkma.py` is a
snapshot. It will drift as HKMA adds and retires datasets. This regenerates it
the way it was built the first time: read the documentation index, take the
endpoint slugs it links to, then ask the live API for one row of each and keep
only the ones that answer with observations.

    uv run python -m scripts.hkma_catalogue

Prints a SECTIONS block to paste into `hkma.py`, and a summary to stderr.
"""

import re
import sys
from collections import defaultdict

from macro_mcp import cache, hkma

DOCS = "https://apidocs.hkma.gov.hk/documentation/market-data-and-statistics/"

# The 4/s this once paced itself at now lives in transport.HOSTS, where the
# server obeys it too. HKMA starts answering 502 when asked in parallel, and it
# does not distinguish a script from a session.


def _page(url: str) -> str:
    r = cache.session().get(url, timeout=cache.TIMEOUT)
    r.raise_for_status()
    return r.text


def sections() -> dict[str, list[str]]:
    """Documentation sections, and the endpoint slugs each links to."""
    index = _page(DOCS)
    found = {}
    for path in sorted(set(re.findall(
            r'href="(/documentation/market-data-and-statistics/[^"#]+)"', index))):
        if path.rstrip("/").endswith("market-data-and-statistics"):
            continue
        slugs = sorted(set(re.findall(r'href="\./([\w\-]+)"', _page(f"https://apidocs.hkma.gov.hk{path}"))))
        if slugs:
            found[path.strip("/").replace("documentation/market-data-and-statistics/", "")] = slugs
    return found


def usable(section: str, slug: str) -> str:
    """The period column, or "" if this slug is not a queryable time series."""
    url = f"{hkma.BASE}/{section}/{slug}"
    try:
        body = cache.session().get(url, params={"pagesize": 1}, timeout=cache.TIMEOUT).json()
    except Exception as e:
        return f"! {type(e).__name__}"
    if not (body.get("header") or {}).get("success"):
        return ""
    rows = (body.get("result") or {}).get("records") or []
    if not rows:
        return ""
    # Section indexes and reference tables come back keyed on something else.
    return next((k for k in rows[0] if k.startswith("end_of")), "")


def main() -> None:
    keep, dropped = defaultdict(list), 0
    for section, slugs in sections().items():
        for slug in slugs:
            if usable(section, slug).startswith("end_of"):
                keep[section].append(slug)
            else:
                dropped += 1
        print(f"{len(keep[section]):>4} kept  {section}", file=sys.stderr)

    total = sum(len(v) for v in keep.values())
    print(f"\n{total} datasets, {dropped} skipped as not time series", file=sys.stderr)
    if set(k for v in keep.values() for k in v) == set(hkma.FLOWS):
        print("identical to the committed table", file=sys.stderr)

    print("SECTIONS = {")
    for section in sorted(keep):
        print(f'    "{section}": (')
        line = " " * 8
        for slug in keep[section]:
            item = f'"{slug}", '
            if len(line) + len(item) > 92:
                print(line.rstrip())
                line = " " * 8
            line += item
        print(line.rstrip())
        print("    ),")
    print("}")


if __name__ == "__main__":
    main()
