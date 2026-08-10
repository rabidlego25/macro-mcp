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

# Every path that carries observations rather than structure. `*/data/*` covers
# SDMX REST; the others are the adapters, whose data paths are named differently
# and would otherwise inherit the week-long metadata TTL.
EXPIRY = {
    "*/data/*": 0,
    "*/tabledata/*": 0,          # SINGSTAT
    "api.hkma.gov.hk/*": 0,      # HKMA serves data and metadata from one path
    "*": TTL,
}
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
