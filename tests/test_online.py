"""Online-event detection.

Real titles from the live site, which is the point: every "should be online"
case below was published on the front page as an event *in Nice*, because
meetup.py did `town = venue.city or "Nice"` and online events have no city.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from niceevents.db import _MIGRATIONS, connect
from niceevents.models import Event
from niceevents.scrapers.meetup import _is_online


def _obj(**kw):
    base = {"title": "Thing", "dateTime": "2099-01-01T18:00:00+01:00"}
    base.update(kw)
    return base


# --- things that really were online, taken verbatim from events.json --------
@pytest.mark.parametrize("title,venue", [
    ("[ONLINE] Informative session for Startups - TAAC 10 Pitch Competition", "Online event"),
    ("[Online] SIA: Angel Investing 101: Learn, Invest, Connect", "Online event"),
    ("🍸 Aperi Business Online", "Online event"),
    ("B2B Creators Meetup (virtual)", "Online event"),
    ("Better Call Claude (Cowork) #1 [En ligne]", "Online event"),
    ("ONLINE!!! Atelier français-anglais / French-English Conversation Workshop", "Online event"),
])
def test_real_online_events_are_detected(title, venue):
    assert _is_online(_obj(title=title), venue, title) is True


def test_structured_flags_win_even_with_an_innocent_venue():
    assert _is_online(_obj(isOnline=True), "Somewhere", "Thing") is True
    assert _is_online(_obj(eventType="ONLINE"), "Somewhere", "Thing") is True


# --- and the false positives that would hide real events -------------------
@pytest.mark.parametrize("title", [
    "Online Marketing Workshop",        # a real room, real chairs
    "Building an Online Business",
    "Zoom Lens Photography Walk",       # "zoom" the camera part
    "Le Chemin de Nietzsche",
])
def test_physical_events_mentioning_online_are_not_flagged(title):
    """A bare "online" in a title is not evidence. Marking these online would
    hide genuine Nice events behind an unticked checkbox — a worse failure than
    showing a stray webinar."""
    assert _is_online(_obj(title=title), "Some Venue, Nice", title) is False


def test_no_venue_and_no_markers_is_not_online():
    assert _is_online(_obj(title="Apéro"), None, "Apéro") is False


# --- the flag has to survive the round trip to SQLite -----------------------
def test_online_column_is_migrated_onto_an_existing_db(tmp_path):
    """The committed events.db predates this column. CREATE TABLE IF NOT EXISTS
    won't add it, so without the ALTER the flag silently vanishes on write."""
    p = tmp_path / "events.db"

    with connect(p) as conn:
        conn.execute("ALTER TABLE events DROP COLUMN online")   # simulate the old db
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(events)")}
        assert "online" not in cols

    with connect(p) as conn:                                    # reopen -> migrate
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(events)")}
        assert "online" in cols


def test_online_flag_survives_a_write_and_read(tmp_path):
    from niceevents import db

    ev = Event(title="Zoom thing", start=date.today() + timedelta(days=3),
               town="Online", source="meetup", online=True)
    offline = Event(title="Real thing", start=date.today() + timedelta(days=3),
                    town="Nice", source="meetup")

    with connect(tmp_path / "e.db") as conn:
        db.upsert(conn, [ev, offline])
        rows = {r["title"]: r["online"] for r in db.upcoming(conn)}

    assert rows["Zoom thing"] == 1
    assert rows["Real thing"] == 0


def test_migrations_list_has_no_duplicates():
    names = [c for c, _ in _MIGRATIONS]
    assert len(names) == len(set(names))
