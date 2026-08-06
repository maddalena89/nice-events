"""Build-time collapse of same-title / same-town overlapping events."""
from __future__ import annotations

from datetime import date

from niceevents.site import _collapse_overlaps, _collapse_recurring

#: Every recurring test pins "today" so the near-window behaviour is deterministic
#: rather than drifting into a pass or a fail depending on the day it is run.
TODAY = date(2026, 7, 1)


def _pipeline(evs, today=TODAY):
    return _collapse_recurring(_collapse_overlaps(evs), today=today)


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


def test_recurring_far_dates_fold_into_one():
    # A guided tour on separate dates, all beyond the near window -> a single row.
    evs = [
        {"title": "Visite guidée Matisse", "town": "Nice", "venue": "Musée Matisse", "start": "2026-10-25"},
        {"title": "Visite guidée Matisse", "town": "Nice", "venue": "Musée Matisse", "start": "2026-11-01"},
        {"title": "Visite guidée Matisse", "town": "Nice", "venue": "Musée Matisse", "start": "2026-12-05"},
    ]
    out = _pipeline(evs)
    assert len(out) == 1
    e = out[0]
    assert e["start"] == "2026-10-25"          # anchored on the first of them
    assert not e.get("end")                    # single day, not a continuous range
    assert "Also on" in (e.get("note") or "")  # other dates noted


def test_recurring_near_dates_keep_their_own_row():
    # THE TANGO BUG. A weekly milonga inside the near window must appear on every
    # night it runs. Folding these into one row published 6 of 41 real milongas.
    evs = [
        {"title": "Milonga de la Estacion", "town": "Nice", "venue": "35 av Malaussena",
         "start": f"2026-07-{d:02d}"} for d in (5, 12, 19, 26)
    ]
    out = _pipeline(evs)
    assert [e["start"] for e in out] == [
        "2026-07-05", "2026-07-12", "2026-07-19", "2026-07-26"]
    assert not any(e.get("recurring") for e in out)


def test_recurring_splits_near_rows_from_a_folded_tail():
    # Two nights inside the window stay real; everything past it folds into one.
    evs = [
        {"title": "Practica", "town": "Nice", "venue": "8 rue Gaston Charbonnier",
         "start": s} for s in ("2026-07-02", "2026-07-09",
                               "2026-09-03", "2026-09-10", "2026-09-17")
    ]
    out = _pipeline(evs)
    assert [e["start"] for e in out] == ["2026-07-02", "2026-07-09", "2026-09-03"]
    assert out[-1]["recurring"] is True
    assert "Also on 10 Sep, 17 Sep" in out[-1]["note"]


def test_consecutive_nights_are_one_run_not_a_repeat():
    # A theatre show playing three nights in a row is one thing, not three cards.
    evs = [
        {"title": "Laponie", "town": "Antibes", "venue": "anthéa", "start": s}
        for s in ("2026-07-10", "2026-07-11", "2026-07-12")
    ]
    out = _pipeline(evs)
    assert len(out) == 1
    assert out[0]["start"] == "2026-07-10" and out[0]["end"] == "2026-07-12"


def test_a_gap_night_splits_the_run():
    # "8, 9, 11 et 12 décembre": the 10th is dark, so this is two runs, not one
    # block that wrongly claims the theatre is open on the 10th.
    evs = [
        {"title": "Casse-Noisette", "town": "Antibes", "venue": "anthéa", "start": s}
        for s in ("2026-07-08", "2026-07-09", "2026-07-11", "2026-07-12")
    ]
    out = _pipeline(evs)
    assert [(e["start"], e.get("end")) for e in out] == [
        ("2026-07-08", "2026-07-09"), ("2026-07-11", "2026-07-12")]


def test_recurring_no_venue_kept():
    # No venue -> can't tell a repeat from a coincidence, so leave them apart.
    evs = [
        {"title": "Cours de salsa", "town": "Nice", "start": "2026-07-24"},
        {"title": "Cours de salsa", "town": "Nice", "start": "2026-07-31"},
    ]
    assert len(_pipeline(evs)) == 2


def test_recurring_different_venue_kept():
    # Same generic name, different places -> two different events.
    evs = [
        {"title": "Brocante", "town": "Nice", "venue": "Place Garibaldi", "start": "2026-07-05"},
        {"title": "Brocante", "town": "Nice", "venue": "Cours Saleya", "start": "2026-07-12"},
    ]
    assert len(_pipeline(evs)) == 2
