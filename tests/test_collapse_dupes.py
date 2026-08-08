"""Same gig, two entries, different titles: the fingerprint (title+date+town)
lets them both through, so a venue-keyed collapse folds them back together —
but only when a community submission is involved, so two genuinely different
acts at one venue on one night are never merged.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from niceevents import db
from niceevents.models import Event

DAY = date.today() + timedelta(days=10)


@pytest.fixture()
def conn(tmp_path):
    with db.connect(tmp_path / "t.db") as c:
        yield c


def _seed(title, venue="La Cave Romagnan", town="Nice"):
    return Event(title=title, start=DAY, town=town, venue=venue,
                 category="concert", source="seed")


def _sub(title, venue="La Cave Romagnan, 22 rue d'Angleterre, 06000 Nice", town="Nice"):
    return Event(title=title, start=DAY, town=town, venue=venue,
                 category="concert", source="submissions", submitted_by="community")


def test_submission_collapses_into_the_established_row(conn):
    db.upsert(conn, [_seed("Claudia Fiddicke & Dmitrij Koscheew (Duo Jazz pur & Ko)")])
    db.upsert(conn, [_sub("Jazz chez Manu")])
    assert len(conn.execute("SELECT 1 FROM events").fetchall()) == 2   # two fingerprints

    removed = db.collapse_venue_duplicates(conn)
    assert removed == 1

    rows = conn.execute("SELECT title, venue, sources FROM events").fetchall()
    assert len(rows) == 1
    # The established (non-submission) row keeps its title...
    assert rows[0]["title"].startswith("Claudia Fiddicke")
    # ...and gains the fuller venue string and both sources.
    assert "22 rue d'Angleterre" in rows[0]["venue"]
    assert "seed" in rows[0]["sources"] and "submissions" in rows[0]["sources"]


def test_two_submissions_of_the_same_gig_collapse(conn):
    db.upsert(conn, [_sub("Jazz chez Manu", venue="La Cave Romagnan")])
    db.upsert(conn, [_sub("Duo Jazz pur & Ko", venue="La Cave Romagnan, 22 rue d'Angleterre")])
    assert db.collapse_venue_duplicates(conn) == 1
    assert len(conn.execute("SELECT 1 FROM events").fetchall()) == 1


def test_two_distinct_scraped_events_at_one_venue_are_left_alone(conn):
    # No submission in the group -> never touched, even though venue+night match.
    db.upsert(conn, [_seed("Opening act")])
    db.upsert(conn, [_seed("Headliner")])
    assert db.collapse_venue_duplicates(conn) == 0
    assert len(conn.execute("SELECT 1 FROM events").fetchall()) == 2
