"""Build-time collapse of same-title / same-town overlapping events."""
from __future__ import annotations

from niceevents.site import _collapse_overlaps


def test_multiday_and_perday_collapse_to_one():
    # A curated multi-day run + a scraper's per-night copies of the same show.
    evs = [
        {"title": "Les Contes d'apéro", "town": "Nice", "start": "2026-07-19",
         "end": "2026-07-26", "venue": "Kiosque du TNN", "note": "19h nightly", "free": True},
        {"title": "Les Contes d’apéro", "town": "Nice", "start": "2026-07-20",
         "note": "19:00 · Théâtre", "free": True},
        {"title": "Les Contes d’apéro", "town": "Nice", "start": "2026-07-21", "free": True},
    ]
    out = _collapse_overlaps(evs)
    assert len(out) == 1
    e = out[0]
    assert e["start"] == "2026-07-19" and e["end"] == "2026-07-26"
    assert e["venue"] == "Kiosque du TNN"     # filled from the richest member


def test_nonoverlapping_repeats_are_kept():
    # A weekly class on separate nights must NOT be merged.
    evs = [
        {"title": "Cours de salsa", "town": "Nice", "start": "2026-07-24", "free": False},
        {"title": "Cours de salsa", "town": "Nice", "start": "2026-07-31", "free": False},
    ]
    out = _collapse_overlaps(evs)
    assert len(out) == 2


def test_different_titles_untouched():
    # Belaprem umbrella vs per-night acts have different titles -> not grouped.
    evs = [
        {"title": "Belaprem", "town": "Nice", "start": "2026-07-01", "end": "2026-07-31"},
        {"title": "Belaprem — Do Brasil", "town": "Nice", "start": "2026-07-23"},
    ]
    out = _collapse_overlaps(evs)
    assert len(out) == 2


def test_different_towns_not_merged():
    evs = [
        {"title": "Expo", "town": "Nice", "start": "2026-07-01", "end": "2026-07-30"},
        {"title": "Expo", "town": "Menton", "start": "2026-07-10"},
    ]
    out = _collapse_overlaps(evs)
    assert len(out) == 2
