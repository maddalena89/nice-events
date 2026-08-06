"""A show that MOVES must not leave its old date advertised.

The fingerprint is title + date + town, so a corrected date arrives as a brand
new row and the original survives until its date passes. Real case: Amarras
moved from Friday 14 to Saturday 15 August 2026 and both nights would have been
on the site.

These tests pin the guards as hard as the behaviour, because the failure mode of
getting this wrong is deleting a real programme, which is far worse than the
stale row it is meant to remove.
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from niceevents import db
from niceevents.models import Event

SOON = date.today() + timedelta(days=10)
LATER = date.today() + timedelta(days=11)


@pytest.fixture()
def conn(tmp_path):
    with db.connect(tmp_path / "t.db") as c:
        yield c


def _ev(title, when, source="tango_argentin", town="Nice", venue="2 rue la Bruyere"):
    return Event(title=title, start=when, town=town, venue=venue,
                 category="danse", source=source)



def test_moved_date_drops_the_old_row(conn):
    db.upsert(conn, [_ev("Amarras", SOON)])
    later = [_ev("Amarras", LATER)]
    db.upsert(conn, later)
    assert db.reconcile_dates(conn, "tango_argentin", later) == 1
    left = [r["start"] for r in conn.execute("SELECT start FROM events")]
    assert left == [LATER.isoformat()]


def test_a_title_the_source_stopped_listing_is_kept(conn):
    # Indistinguishable from a truncated scrape, so never delete on this signal.
    db.upsert(conn, [_ev("Bicilonga", SOON)])
    other = [_ev("Amarras", LATER)]
    db.upsert(conn, other)
    assert db.reconcile_dates(conn, "tango_argentin", other) == 0
    assert conn.execute("SELECT COUNT(*) c FROM events").fetchone()["c"] == 2


def test_row_confirmed_this_run_is_kept(conn):
    evs = [_ev("Amarras", SOON), _ev("Amarras", LATER)]
    db.upsert(conn, evs)
    assert db.reconcile_dates(conn, "tango_argentin", evs) == 0


def test_row_another_source_also_saw_is_kept(conn):
    db.upsert(conn, [_ev("Amarras", SOON)])
    db.upsert(conn, [_ev("Amarras", SOON, source="nice_fr")])   # merges, two sources
    later = [_ev("Amarras", LATER)]
    db.upsert(conn, later)
    assert db.reconcile_dates(conn, "tango_argentin", later) == 0


def test_past_rows_are_left_to_prune_past(conn):
    gone = date.today() - timedelta(days=3)
    db.upsert(conn, [_ev("Amarras", gone)])
    later = [_ev("Amarras", LATER)]
    db.upsert(conn, later)
    assert db.reconcile_dates(conn, "tango_argentin", later) == 0


def test_empty_run_never_deletes_anything(conn):
    db.upsert(conn, [_ev("Amarras", SOON), _ev("Bicilonga", LATER)])
    assert db.reconcile_dates(conn, "tango_argentin", []) == 0
    assert conn.execute("SELECT COUNT(*) c FROM events").fetchone()["c"] == 2


def test_human_submissions_are_never_touched(conn):
    ev = _ev("Amarras", SOON)
    ev.submitted_by = "someone@example.com"
    db.upsert(conn, [ev])
    later = [_ev("Amarras", LATER)]
    db.upsert(conn, later)
    assert db.reconcile_dates(conn, "tango_argentin", later) == 0


def test_only_opt_in_scrapers_reconcile():
    """Which sources may delete rows, checked in a CLEAN interpreter.

    Not `from niceevents.scrapers import REGISTRY` in-process: @register fires on
    import, so any other test that imports a scraper module directly puts it in
    the registry and this assertion silently passes on something production never
    loads. That is exactly how it went green while tango was retired.
    """
    import subprocess
    import sys

    r = subprocess.run(
        [sys.executable, "-c",
         "from niceevents.scrapers import REGISTRY;"
         "print(sorted(n for n, c in REGISTRY.items() if c.reconciles_dates));"
         "print(sorted(REGISTRY))"],
        capture_output=True, text=True, cwd=str(Path(__file__).resolve().parent.parent),
    )
    assert r.returncode == 0, r.stderr
    reconciling, registered = r.stdout.strip().splitlines()

    assert reconciling == "['anthea']", (
        "reconcile_dates deletes rows: only enable it for a source you have "
        f"checked returns its complete listing every run. Got {reconciling}")
    assert "tango_argentin" not in registered, (
        "tango-argentin.fr was retired because it does not publish cancellations; "
        "tango comes from the Agenda Tango Argentin via harvest")
