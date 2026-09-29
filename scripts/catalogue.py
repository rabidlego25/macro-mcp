"""Build the cross-provider dataflow index.

`find_dataflows` searches one provider. An agent that does not already know
which provider carries a subject has no way to ask: an eval asked IMF for
unemployment, got `total: 0`, and had no reason to think ILO had 108 flows for
it. Fanning out live is not the answer — a cold catalogue read costs 20s from
ISTAT and 50s from Eurostat, and 29 of those is not a tool call.

So the catalogue is built once, here, and shipped. It holds ids and names only,
which is all a routing question needs, and it is a hint rather than an answer:
what it says has to be confirmed with a real `find_dataflows` against the
provider it names, so a stale index can misroute but cannot return a stale
answer.

    MACRO_MCP_NO_CACHE=1 uv run python -m scripts.catalogue

Writes src/macro_mcp/catalogue.json.gz and prints a summary to stderr.
"""

import gzip
import json
import pathlib
import sys
import time
from concurrent.futures import ThreadPoolExecutor

from macro_mcp import sdmx_api as api

OUT = pathlib.Path(api.__file__).parent / "catalogue.json.gz"

# Providers are separate hosts and the transport paces each one, so they are
# read together. Sequentially this takes a quarter of an hour.
WORKERS = 6


def names(obj) -> list[str]:
    """Every localization, deduplicated, English first.

    ISTAT names a flow `Coltivazioni` and `Crops` and the index has to match
    both, which is the same reason the live search reads every localization.
    Identical strings across languages are kept once.
    """
    got = api._names(obj)
    label = api._label(got)
    rest = [n for n in got.values() if n != label]
    return [label, *dict.fromkeys(rest)] if label else []


def read(provider: str) -> tuple[str, list, str]:
    started = time.monotonic()
    try:
        if provider in api.NATIVE:
            # The adapters hold their catalogues locally or need a search term;
            # neither is a dataflow list to index. SingStat is a search
            # endpoint, not a catalogue, and HKMA's list is already in the repo.
            return provider, [], "adapter: not indexed"
        if not api._supports(provider, "dataflow"):
            return provider, [], "serves no dataflow metadata"
        # A flow with no localization at all falls back to its id, so every
        # row in the index has something to match and something to show. None
        # of the 27,190 needs it today; the invariant is what the loader and
        # its tests rely on.
        flows = [[k, *(names(v) or [k])] for k, v in api._flows(provider).items()]
        return provider, flows, f"{len(flows)} flows in {time.monotonic() - started:.0f}s"
    except Exception as e:
        return provider, [], f"{type(e).__name__}: {e}"[:100]


# A rebuild that finds a provider down, or finds far fewer flows than last
# time, keeps the previous entries for it. It runs unattended on a schedule,
# and one bad morning at Eurostat would otherwise drop 8,000 flows from search
# until someone noticed.
SHRINK = 0.8


def previous() -> dict:
    try:
        return json.loads(gzip.decompress(OUT.read_bytes()))
    except (OSError, ValueError):
        return {}


def guarded(rows: list, before: dict) -> tuple[dict, list]:
    index, notes = {}, []
    for p, flows, note in rows:
        old = before.get(p, [])
        if old and len(flows) < SHRINK * len(old):
            index[p] = old
            notes.append((p, len(old), f"kept {len(old)} from the previous build; "
                                       f"this one found {len(flows)} ({note})"))
        else:
            if flows:
                index[p] = flows
            notes.append((p, len(flows), note))
    return index, notes


def main() -> None:
    providers = [p for ps in api.GROUPS.values() for p in ps]
    with ThreadPoolExecutor(WORKERS) as pool:
        rows = list(pool.map(read, providers))

    last = previous()
    index, notes = guarded(rows, last.get("providers", {}))
    # The date moves only when the catalogue does, so an unchanged rebuild
    # leaves the file byte for byte as it was and a scheduled job commits
    # nothing. gzip stamps the time too unless told not to.
    same = index == last.get("providers")
    payload = {"built": last["built"] if same else time.strftime("%Y-%m-%d"), "providers": index}
    blob = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    OUT.write_bytes(gzip.compress(blob, 9, mtime=0))

    for p, n, note in notes:
        print(f"{p:<14} {n:>6}  {note}", file=sys.stderr)
    if same:
        print("\nno catalogue changed since the last build", file=sys.stderr)
    print(f"\n{sum(len(f) for f in index.values())} flows from {len(index)} "
          f"providers\n{len(blob) / 1e6:.1f}MB raw, {OUT.stat().st_size / 1e6:.1f}MB "
          f"gzipped -> {OUT}", file=sys.stderr)


if __name__ == "__main__":
    main()
