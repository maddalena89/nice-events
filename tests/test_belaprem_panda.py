"""Belaprem + Panda curated sources — registration, shape, past-date drop."""
from __future__ import annotations

from datetime import date

from niceevents.scrapers import REGISTRY
from niceevents.scrapers.belaprem import NIGHTS, Belaprem
from niceevents.scrapers.panda import SHOWS, Panda


def test_registered():
    assert "belaprem" in REGISTRY
    assert "panda" in REGISTRY


def test_belaprem_nights_well_formed():
    for day, act, slot, activity in NIGHTS:
        assert 1 <= day <= 31
        assert act and slot and activity
    # every Belaprem night is free and a concert, in Nice, at Le 109
    for e in Belaprem().fetch():
        assert e.free is True
        assert e.category == "concert"
        assert e.town == "Nice"
        assert e.source == "belaprem"
        assert (e.end or e.start) >= date.today()


def test_panda_shows_well_formed():
    seen = set()
    for start_s, title, town, venue, price, free, slug in SHOWS:
        date.fromisoformat(start_s)          # valid ISO date
        assert title and town and slug
        assert slug not in seen, f"duplicate slug {slug}"
        seen.add(slug)


def test_panda_drops_past_and_tags_source():
    today = date.today()
    for e in Panda().fetch():
        assert e.start >= today
        assert e.source == "panda"
        assert e.url.startswith("https://www.panda-events.com/evenement/")


def test_panda_has_a_free_gig_flagged():
    # Dje Baleti is the gratuit one — make sure the free flag survives.
    free_titles = {t for (_s, t, _tn, _v, _p, f, _sl) in SHOWS if f}
    assert any("Dje Baleti" in t for t in free_titles)
