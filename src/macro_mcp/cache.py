"""Disk cache for provider metadata.

Dataflow lists and structures are large and slow to build — ISTAT takes about
two minutes cold — and providers republish them rarely. In-process memoisation
dies with the process, which for an MCP server means every session pays that
cost again from scratch.

Observations are never served from cache: `*/data/*` is the SDMX REST data path
on every provider here, BBK included, and it is pinned to expire immediately.
Stale metadata is a minor annoyance; a stale exchange rate is a wrong answer.
"""

import os
from functools import lru_cache
from pathlib import Path

from sdmx.session import Session

TTL = 7 * 24 * 3600

# Paths carrying observations. These come first because the first matching
# pattern wins and BIS puts /data/dataflow/ in its *data* URLs, which the
# structure patterns below would otherwise claim.
DATA = ("*/data/*", "*/tabledata/*")

# SDMX structure resources, plus SINGSTAT's catalogue search. These change
# rarely and are expensive to rebuild.
STRUCTURE = ("dataflow", "datastructure", "codelist", "conceptscheme",
             "categoryscheme", "categorisation", "agencyscheme",
             "contentconstraint", "resourceid")

# Default deny. Naming the data paths instead would fail open: a new adapter
# whose data path nobody remembered to list would quietly serve week-old
# numbers, which is how SINGSTAT's /tabledata/ slipped through. Forgetting to
# declare a path now costs a round trip rather than correctness.
EXPIRY = {**{p: 0 for p in DATA},
          **{f"*/{r}*": TTL for r in STRUCTURE},
          "*": 0}
TIMEOUT = 180.0
USER_AGENT = "macro-mcp/0.1 (+https://github.com/topics/sdmx)"


def path() -> Path:
    root = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    return root / "macro-mcp" / "http"


@lru_cache(maxsize=1)
def session() -> Session:
    """Shared across sdmx1 and the Bundesbank adapter, so both cache alike.

    Set MACRO_MCP_NO_CACHE=1 to bypass; the live tests do, since a cached
    dataflow list would let them pass against a provider that has since moved.
    """
    if os.environ.get("MACRO_MCP_NO_CACHE") == "1":
        return _identify(Session(timeout=TIMEOUT))
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    return _identify(Session(timeout=TIMEOUT, backend="sqlite", cache_name=str(p),
                             urls_expire_after=EXPIRY))


def _identify(s: Session) -> Session:
    """SingStat rejects the default python-requests agent with a 403, and
    naming the client is the courteous thing to do besides."""
    s.headers["User-Agent"] = USER_AGENT
    return s
