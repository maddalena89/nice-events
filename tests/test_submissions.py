"""Community submissions: registration, mapping, and the security boundary.

The first test here exists because the scraper was written, worked, and was
never imported in scrapers/__init__.py — so REGISTRY didn't have it and it
silently never ran. Nothing failed. There was simply no such source, forever.
A registry that's a hand-maintained list of imports needs a test that reads the
directory instead.
"""
from __future__ import annotations

import importlib
import os
import pkgutil
from datetime import date, timedelta

import pytest

from niceevents.scrapers import REGISTRY
from niceevents.scrapers.submissions import Submissions


def test_every_scraper_module_is_imported_by_the_package():
    """Every module in scrapers/ must be imported by __init__.py.

    Catches the "wrote it, forgot to import it" failure, which is invisible at
    runtime — an unregistered source looks exactly like a source that found no
    events.

    Note this checks *imported*, not "module name is a REGISTRY key": the two
    differ on purpose (tango.py registers as `tango_argentin`). Importing is the
    thing that runs @register, so importing is the thing to assert.
    """
    import niceevents.scrapers as pkg

    skip = {"base"}
    on_disk = {
        m.name for m in pkgutil.iter_modules(pkg.__path__)
        if not m.name.startswith("_") and m.name not in skip
    }
    missing = {name for name in on_disk if not hasattr(pkg, name)}
    assert not missing, f"scraper modules never imported in __init__.py: {sorted(missing)}"


def test_submissions_is_registered():
    assert "submissions" in REGISTRY


def _row(**kw):
    row = {
        "id": "00000000-0000-0000-0000-000000000001",
        "title": "Milonga at the port",
        "start_date": "2099-01-01",
        "end_date": None,
        "town": "nice",
        "venue": "Quai Lunel",
        "category": "danse",
        "url": "https://example.org/milonga",
        "note": None,
    }
    row.update(kw)
    return row


def test_maps_a_row_to_an_event():
    ev = Submissions()._to_event(_row(), date(2026, 7, 15))
    assert ev is not None
    assert ev.title == "Milonga at the port"
    assert ev.town == "Nice"                 # canon_town applied
    assert ev.category == "danse"
    assert ev.source == "submissions"
    assert ev.submitted_by == "community"
    assert ev.approved is True


def test_unknown_category_falls_back_rather_than_dropping_the_event():
    """A taxonomy mismatch must not silently delete someone's event."""
    ev = Submissions()._to_event(_row(category="not_a_real_category"), date(2026, 7, 15))
    assert ev is not None
    assert ev.category == "autre"


def test_finished_events_are_dropped_but_running_ones_are_kept():
    today = date(2026, 7, 15)
    over = _row(start_date="2026-07-01", end_date="2026-07-10")
    assert Submissions()._to_event(over, today) is None

    # Started in the past, still running — an exhibition, not a mistake.
    running = _row(start_date="2026-07-01", end_date="2026-07-30")
    assert Submissions()._to_event(running, today) is not None


def test_row_with_no_usable_date_is_skipped_not_crashed():
    assert Submissions()._to_event(_row(start_date=""), date(2026, 7, 15)) is None
    assert Submissions()._to_event(_row(title="  "), date(2026, 7, 15)) is None


def test_yields_nothing_without_credentials(monkeypatch):
    """A fresh clone with no Supabase configured must build, not explode."""
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_KEY", raising=False)
    assert list(Submissions().fetch()) == []


def test_email_is_never_requested_from_the_database():
    """The submitter's email must not be loadable into a public events feed.

    Enforced by not selecting the column at all — the surest way not to leak a
    value is never to hold it.
    """
    from niceevents.scrapers import submissions as mod
    assert "email" not in mod._COLS.split(",")


def test_site_module_cannot_see_the_service_key(monkeypatch):
    """site.py renders a PUBLIC html file. The RLS-bypassing key must not be
    reachable from it, even by accident."""
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "super-secret-do-not-ship")
    import niceevents.site as site
    importlib.reload(site)
    source = open(site.__file__, encoding="utf-8").read()
    assert "SERVICE_KEY" not in source
    for name in dir(site):
        val = getattr(site, name)
        if isinstance(val, str):
            assert "super-secret-do-not-ship" not in val
