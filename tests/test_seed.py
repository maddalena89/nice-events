"""Curated seed source — sanity + the past-date drop."""
from __future__ import annotations

from datetime import date, timedelta

from niceevents.scrapers import REGISTRY
from niceevents.scrapers.seed import SEED, Seed


def test_registered():
    assert "seed" in REGISTRY


def test_rows_are_well_formed():
    for row in SEED:
        start, end, title, town, venue, cat, note, url, free = row   # 9-tuple shape
        date.fromisoformat(start)
        if end:
            date.fromisoformat(end)
        assert title and town and url
        assert cat in {"expo", "concert", "scene", "danse", "brocante",
                       "visite", "atelier", "business", "social", "sport",
                       "marche", "autre"}


def test_past_events_are_dropped():
    evs = list(Seed().fetch())
    today = date.today()
    for e in evs:
        assert (e.end or e.start) >= today
    # everything still current should survive
    assert all(e.source == "seed" for e in evs)


def test_covers_the_towns_scrapers_miss():
    towns = {e.town for e in Seed().fetch()}
    # the whole point: coast & border towns the daily scrapers don't reach
    for t in ("Menton", "Monaco", "Beaulieu-sur-Mer", "Saint-Paul-de-Vence"):
        assert t in towns or all(
            (date.fromisoformat(r[1] or r[0]) < date.today()) for r in SEED if r[3] == t
        )
