"""Pacing and retry, which exist because two providers taught them.

HKMA answered 502 on every path for minutes after eight parallel requests, and
ISTAT returns intermittent 500s that the next request answers normally. Both
reach the agent as a plain failure unless something here absorbs them, so these
assert on what was sent — how many requests, how far apart, and whether they
overlapped — rather than on the response alone.
"""

import io
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
import requests
import urllib3
from requests.adapters import HTTPAdapter
from sdmx.session import Session

from macro_mcp import cache, transport

URL = "https://example.test/dataflow/x"


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    """Hosts are process-wide state, and the backoff is real sleeping."""
    transport._hosts.clear()
    monkeypatch.setattr(transport, "BACKOFF", 0.001)
    yield
    transport._hosts.clear()


@pytest.fixture
def network(monkeypatch):
    """Script the wire. Each step is a status, a (status, headers) pair, or an
    exception to raise; the last step repeats once the script runs out."""
    sent = []

    def install(*script):
        queue = list(script)

        def fake(self, request, **kwargs):
            sent.append((request.method, time.monotonic()))
            step = queue.pop(0) if len(queue) > 1 else queue[0]
            if isinstance(step, Exception):
                raise step
            status, headers = step if isinstance(step, tuple) else (step, {})
            raw = urllib3.HTTPResponse(body=io.BytesIO(b"{}"), status=status,
                                       headers=headers, preload_content=False,
                                       request_url=request.url)
            return HTTPAdapter.build_response(self, request, raw)

        monkeypatch.setattr(HTTPAdapter, "send", fake)
        return sent

    return install


def client() -> requests.Session:
    s = requests.Session()
    s.mount("https://", transport.Adapter())
    return s


def test_a_transient_500_is_retried_and_the_good_answer_returned(network):
    sent = network(500, 200)
    assert client().get(URL).status_code == 200
    assert len(sent) == 2


def test_retries_are_bounded_and_the_last_failure_is_returned(network):
    """Not raised. A 503 that survives the retries is the provider's answer,
    and the caller's own error handling — HKMA's 404 message, GLEIF's missing
    parent — reads status codes, not exceptions."""
    sent = network(503)
    assert client().get(URL).status_code == 503
    assert len(sent) == transport.ATTEMPTS


def test_a_dropped_connection_is_retried_and_then_raised(network):
    sent = network(requests.exceptions.ConnectionError("reset by peer"))
    with pytest.raises(requests.exceptions.ConnectionError):
        client().get(URL)
    assert len(sent) == transport.ATTEMPTS


def test_a_request_this_client_composed_wrongly_is_not_repeated(network):
    """404 is the answer, not a hiccup. Repeating it only doubles the load."""
    sent = network(404)
    assert client().get(URL).status_code == 404
    assert len(sent) == 1


def test_a_write_is_never_sent_twice(network):
    """Nothing here writes today; this is the guard for the adapter that does."""
    sent = network(503)
    assert client().post(URL).status_code == 503
    assert len(sent) == 1


def test_retry_after_is_preferred_to_the_backoff():
    response = requests.Response()
    response.headers["Retry-After"] = "7"
    assert transport.pause(0, response) == 7.0
    assert transport.retry_after(requests.Response()) is None


def test_retry_after_may_be_a_date():
    response = requests.Response()
    response.headers["Retry-After"] = "Wed, 21 Oct 2015 07:28:00 GMT"
    assert transport.retry_after(response) == 0.0  # in the past, so no wait


def test_an_unreadable_retry_after_falls_back_to_the_backoff():
    response = requests.Response()
    response.headers["Retry-After"] = "soon"
    assert 0 < transport.pause(0, response) <= transport.BACKOFF * 1.5


def test_being_told_to_wait_holds_back_the_whole_host(network):
    """A 429 is addressed to the client, not to the thread that drew it, so the
    requests queued behind it are being told the same thing."""
    network((429, {"Retry-After": "0.2"}), 200)
    gate = transport.host("example.test")
    started = time.monotonic()
    client().get(URL)
    assert time.monotonic() - started >= 0.2
    assert gate.free_at > time.monotonic() - 0.2  # the hold outlives the call


def test_hkma_is_asked_one_at_a_time():
    """Its own documented failure: eight in parallel and it stops answering."""
    assert transport.HOSTS["api.hkma.gov.hk"].parallel == 1
    assert transport.HOSTS["api.hkma.gov.hk"].interval == 0.25


def test_a_serial_host_never_has_two_requests_in_flight():
    gate = transport.Host(transport.Limit(interval=0, parallel=1))
    peak, live, lock = 0, 0, threading.Lock()

    def hit():
        nonlocal peak, live
        with gate.slot():
            with lock:
                live += 1
                peak = max(peak, live)
            time.sleep(0.01)
            with lock:
                live -= 1

    with ThreadPoolExecutor(4) as pool:
        list(pool.map(lambda _: hit(), range(8)))
    assert peak == 1


def test_a_paced_host_spaces_requests_out():
    gate = transport.Host(transport.Limit(interval=0.05, parallel=4))
    at = []
    for _ in range(3):
        with gate.slot():
            at.append(time.monotonic())
    assert all(b - a >= 0.05 for a, b in zip(at, at[1:]))


def test_an_unlisted_host_is_capped_but_not_slowed():
    gate = transport.host("api.gleif.org")
    assert gate.limit == transport.DEFAULT
    assert gate.limit.interval == 0


def test_hosts_do_not_queue_behind_each_other():
    slow = transport.Host(transport.Limit(interval=5, parallel=1))
    with slow.slot():
        pass
    started = time.monotonic()
    with transport.host("api.gleif.org").slot():
        pass
    assert time.monotonic() - started < 0.05


def test_a_cached_read_never_reaches_the_transport(network):
    """The reason the adapter is mounted rather than wrapping the session: a
    week-old structure should not queue behind a live request, or spend a slot
    on a host that is being throttled."""
    sent = network(200)
    s = cache._prepare(Session(timeout=5, backend="memory",
                               urls_expire_after={"*": 60}))
    assert s.get(URL).status_code == 200
    assert s.get(URL).from_cache
    assert len(sent) == 1


def test_every_session_this_server_builds_is_paced(monkeypatch):
    monkeypatch.setenv("MACRO_MCP_NO_CACHE", "1")
    cache.session.cache_clear()
    try:
        mounted = cache.session().adapters
        assert isinstance(mounted["https://"], transport.Adapter)
        assert isinstance(mounted["http://"], transport.Adapter)
    finally:
        cache.session.cache_clear()


def test_a_certificate_that_will_not_verify_is_not_asked_twice(network):
    """UY110 serves a self-signed one. SSLError is a ConnectionError, so it
    would otherwise be treated as a dropped connection and retried."""
    sent = network(requests.exceptions.SSLError("self-signed certificate"))
    with pytest.raises(requests.exceptions.SSLError):
        client().get(URL)
    assert len(sent) == 1
