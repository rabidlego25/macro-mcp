"""Per-host pacing and retry, applied to every request this server makes.

Two observed failures motivate it. HKMA began answering 502 on every path after
eight parallel requests during this work and did not recover for some minutes,
so a provider can be knocked over by this client alone. And the User-Agent is
shared by every install, so a provider that decides to throttle it throttles
everyone at once — which makes politeness a correctness concern rather than a
courtesy.

It is mounted as a transport adapter rather than wrapped around the session so
that the disk cache is consulted first: a cached structure read waits for
nobody and spends no slot. The state is per process, so several servers on one
machine still do not coordinate.
"""

import random
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit

from requests.adapters import HTTPAdapter
from requests.exceptions import ConnectionError, SSLError, Timeout

ATTEMPTS = 3
BACKOFF = 0.5
MAX_BACKOFF = 30.0

# Transient by convention. 429 and 503 are the service asking to be left alone;
# 500 covers ISTAT, which answers one in several requests that way and the next
# one normally. 4xx other than 429 is a request this client composed wrongly,
# and repeating it only doubles the load.
RETRY_ON = frozenset({429, 500, 502, 503, 504})

# Only methods that can be sent twice without meaning it twice. Everything here
# reads, so this is a guard against a future adapter that writes rather than a
# live constraint.
REPEATABLE = frozenset({"GET", "HEAD", "OPTIONS"})


@dataclass(frozen=True)
class Limit:
    """`interval` is the minimum gap between the starts of two requests to a
    host; `parallel` is how many may be in flight at once."""

    interval: float = 0.0
    parallel: int = 4


# The default is a concurrency cap and no pacing: the point is to bound a burst,
# not to slow down a provider that has never complained.
DEFAULT = Limit()

HOSTS = {
    # Measured, not guessed: eight at once took it down, and 4/s is the rate
    # scripts/hkma_catalogue.py has run at since without a 502.
    "api.hkma.gov.hk": Limit(interval=0.25, parallel=1),
}


class Host:
    """One host's share of the client, held across threads."""

    def __init__(self, limit: Limit):
        self.limit = limit
        self.inflight = threading.BoundedSemaphore(limit.parallel)
        self.clock = threading.Lock()
        self.free_at = 0.0

    def defer(self, seconds: float) -> None:
        """Hold the whole host back, not only the caller.

        A 429 is addressed to this client, not to one of its threads, so the
        requests queued behind it have been told the same thing.
        """
        with self.clock:
            self.free_at = max(self.free_at, time.monotonic() + seconds)

    @contextmanager
    def slot(self):
        with self.inflight:
            while True:
                with self.clock:
                    now = time.monotonic()
                    wait = self.free_at - now
                    if wait <= 0:
                        self.free_at = now + self.limit.interval
                        break
                # Slept outside the lock, so a thread waiting out a backoff does
                # not also block one that is only reading the clock.
                time.sleep(wait)
            yield


_hosts: dict[str, Host] = {}
_registry = threading.Lock()


def host(name: str) -> Host:
    with _registry:
        if name not in _hosts:
            _hosts[name] = Host(HOSTS.get(name, DEFAULT))
        return _hosts[name]


def retry_after(response) -> float | None:
    """The Retry-After header in seconds, or None if it is absent or unreadable.

    It comes as either a count of seconds or an HTTP date, and both are in use.
    """
    value = (response.headers.get("Retry-After") or "").strip() if response is not None else ""
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when is None:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return max(0.0, (when - datetime.now(timezone.utc)).total_seconds())


def pause(attempt: int, response) -> float:
    """What the server asked for, or exponential backoff with jitter.

    The jitter matters more than it looks. Without it, every thread blocked on
    the same 503 wakes at the same instant and repeats the burst that caused it.
    """
    named = retry_after(response)
    if named is not None:
        return min(named, MAX_BACKOFF)
    return min(BACKOFF * 2 ** attempt * (0.5 + random.random()), MAX_BACKOFF)


class Adapter(HTTPAdapter):
    """Paces and retries. Reached only on a cache miss, by construction."""

    def send(self, request, **kwargs):
        gate = host(urlsplit(request.url).hostname or "")
        attempts = ATTEMPTS if request.method in REPEATABLE else 1
        for attempt in range(attempts):
            failure = None
            with gate.slot():
                try:
                    response = super().send(request, **kwargs)
                except SSLError:
                    # A certificate that fails verification fails the same way
                    # twice. UY110 serves a self-signed one, so this is the
                    # difference between a quick answer and three of them.
                    raise
                except (ConnectionError, Timeout) as exc:
                    response, failure = None, exc
            if response is not None and response.status_code not in RETRY_ON:
                return response
            if attempt == attempts - 1:
                if failure is not None:
                    raise failure
                return response
            gate.defer(pause(attempt, response))
            if response is not None:
                # The body is discarded, so return the connection rather than
                # leaving it held open for the length of the backoff.
                response.close()
        raise AssertionError("unreachable: the last attempt returns or raises")
