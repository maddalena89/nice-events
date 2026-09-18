"""A source that cannot be read must not report as an ordinary quiet day.

7 August 2026: the Supabase service key had expired, every submissions read came
back HTTP 401, and sources.json said `status: "empty", error: null` for days
while approved community events sat unpublished. The failure was in the Action
log and nowhere a person would look.
"""
from __future__ import annotations

import sqlite3
from typing import Iterator

import httpx
import pytest

from niceevents import db
from niceevents.models import Event
from niceevents.scrapers.base import HttpScraper
from niceevents.site import _source_report


class _Probe(HttpScraper):
    name = "probe"
    label = "Probe"
    delay = 0.0

    def fetch(self) -> Iterator[Event]:      # pragma: no cover - not used
        return iter(())


def _probe_with(handler) -> _Probe:
    s = _Probe()
    s._client = httpx.Client(transport=httpx.MockTransport(handler))
    return s


# --------------------------------------------------------------------------
# the HTTP layer records why it failed
# --------------------------------------------------------------------------

def test_a_401_is_recorded_with_its_status_and_url():
    s = _probe_with(lambda req: httpx.Response(401))
    assert s.get("https://example.test/rest/v1/submissions") is None
    assert s.fetch_error.startswith("HTTP 401 on https://example.test/")
    assert s.fetch_failures == 1


def test_a_transport_error_is_recorded_by_type():
    def boom(req):
        raise httpx.ConnectError("nope", request=req)
    s = _probe_with(boom)
    assert s.get("https://example.test/x") is None
    assert s.fetch_error.startswith("ConnectError on https://example.test/x")


def test_the_first_failure_is_kept_not_the_last():
    # Later failures are usually knock-ons; the first one names the cause.
    seen = {"n": 0}

    def handler(req):
        seen["n"] += 1
        return httpx.Response(401 if seen["n"] == 1 else 500)

    s = _probe_with(handler)
    s.get("https://example.test/first")
    s.get("https://example.test/second")
    assert "401" in s.fetch_error and "first" in s.fetch_error
    assert s.fetch_failures == 2


def test_a_successful_request_records_nothing():
    s = _probe_with(lambda req: httpx.Response(200, text="ok"))
    assert s.get("https://example.test/x") is not None
    assert s.fetch_error is None
    assert s.fetch_failures == 0


def test_the_error_is_trimmed_so_it_stays_readable_in_a_column():
    s = _probe_with(lambda req: httpx.Response(401))
    s.get("https://example.test/" + "q" * 500)
    assert len(s.fetch_error) <= 160


def test_one_scraper_does_not_infect_another():
    a = _probe_with(lambda req: httpx.Response(401))
    b = _probe_with(lambda req: httpx.Response(200, text="ok"))
    a.get("https://example.test/x")
    b.get("https://example.test/x")
    assert a.fetch_error is not None
    assert b.fetch_error is None      # the default must not be shared state


# --------------------------------------------------------------------------
# and the dashboard says so out loud
# --------------------------------------------------------------------------

def _report(conn, events=()):
    return {s["name"]: s for s in _source_report(conn, list(events))["sources"]}


def test_an_unreadable_source_reads_as_failed_with_the_reason():
    with db.connect(":memory:") as conn:
        db.log_run(conn, "submissions", ok=False, found=0,
                   error="HTTP 401 on https://x.supabase.co/rest/v1/submissions")
        row = _report(conn)["submissions"]
        assert row["status"] == "failed"
        assert "401" in row["error"]


def test_a_genuinely_quiet_source_still_reads_as_empty():
    with db.connect(":memory:") as conn:
        db.log_run(conn, "submissions", ok=True, found=0)
        row = _report(conn)["submissions"]
        assert row["status"] == "empty"
        assert row["error"] is None


def test_a_source_that_published_is_ok_even_after_a_dud_page():
    # One 404 on a detail page must not condemn a run that returned events.
    with db.connect(":memory:") as conn:
        db.log_run(conn, "nice_fr", ok=True, found=2, added=2)
        events = [{"source": "nice_fr", "title": "a"}, {"source": "nice_fr", "title": "b"}]
        row = _report(conn, events)["nice_fr"]
        assert row["status"] == "ok"
        assert row["published"] == 2
