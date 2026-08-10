"""Probe what each provider actually serves, and print the SUPPORTS table.

sdmx1's `source.supports` is a static declaration, not a measurement, so it
disagrees with the live services. This asks them, through the same code paths
the server uses, and prints a dict to paste into sdmx_api.SUPPORTS.

    MACRO_MCP_NO_CACHE=1 uv run python -m scripts.probe
"""

import sys
import time

from macro_mcp import sdmx_api as api

MISSING = object()


def attempt(fn):
    """Twice, because these services are flaky enough that one failure is not
    evidence of a missing endpoint. ESTAT dropped a connection mid-probe and
    would otherwise have been recorded as serving no structure metadata, which
    would have disabled describe_flow for Eurostat permanently.

    A NotImplementedError comes from sdmx1's own routing rather than the
    network, so it is final.
    """
    for last in (False, True):
        try:
            return fn(), ""
        except NotImplementedError as e:
            return MISSING, f"{type(e).__name__}: {e}"
        except Exception as e:
            if last:
                return MISSING, f"{type(e).__name__}: {e}"
            time.sleep(3)


def probe(provider: str) -> tuple[tuple[str, ...], str]:
    flows, err = attempt(lambda: api._flows(provider))
    if err:
        return (), f"dataflow: {err}"[:110]
    if not flows:
        # A 200 with an empty list is not support; it is a dead end the agent
        # would otherwise walk into.
        return (), "dataflow: empty list"

    _, err = attempt(lambda: api._dsd(provider, next(iter(flows))))
    if err:
        return ("dataflow",), f"datastructure: {err}"[:110]
    return ("dataflow", "datastructure"), ""


def main() -> None:
    rows = {}
    for provider in [p for ps in api.GROUPS.values() for p in ps]:
        t = time.time()
        rows[provider], note = probe(provider)
        print(f"{provider:<14} {round(time.time() - t, 1):>6}s  "
              f"{','.join(rows[provider]) or '-':<26} {note}", file=sys.stderr)

    print("\nSUPPORTS = {", file=sys.stderr)
    for p, got in rows.items():
        print(f"    {p!r}: {got!r},", file=sys.stderr)
    print("}", file=sys.stderr)


if __name__ == "__main__":
    main()
