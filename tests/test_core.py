"""Tests for the bits that don't need network: parsing, dedup, merge, build.

The scrapers themselves can only be tested against the live sites, but these
cover the logic that decides whether the output is trustworthy.
"""
from datetime import date

import pytest

from niceevents import db
from niceevents.models import Event, canon_town, classify, parse_date, parse_time


# ------------------------------------------------------------------ dates

@pytest.mark.parametrize("raw,expected", [
    ("2026-07-18", date(2026, 7, 18)),
    ("20260718", date(2026, 7, 18)),              # WP ACF format
    ("18/07/2026", date(2026, 7, 18)),
    ("18 Juillet 2026", date(2026, 7, 18)),       # Brocabrac
    ("2 Août 2026", date(2026, 8, 2)),
    ("1er septembre 2026", date(2026, 9, 1)),
    ("Wednesday 15 July 2026", date(2026, 7, 15)),  # tango-argentin
    ("11 July 2026", date(2026, 7, 11)),
    ("Sat, 11 Jul 2026", date(2026, 7, 11)),       # RA
    ("13 February 2026", date(2026, 2, 13)),
    ("2026-07-23T19:30:00+02:00", date(2026, 7, 23)),  # JSON-LD
])
def test_parse_date(raw, expected):
    assert parse_date(raw) == expected


def test_parse_date_rejects_junk():
    assert parse_date("") is None
    assert parse_date("next tuesday") is None
    assert parse_date("32 Juillet 2026") is None    # invalid day, not a crash


@pytest.mark.parametrize("raw,expected", [
    ("19h30", "19:30"), ("19h", "19:00"), ("8:30pm", "20:30"),
    ("7:00pm", "19:00"), ("12:00am", "00:00"), ("20:45", "20:45"),
])
def test_parse_time(raw, expected):
    assert parse_time(raw) == expected


# ------------------------------------------------------------------ towns

def test_canon_town_variants():
    assert canon_town("NICE") == "Nice"
    assert canon_town("cap-d'ail") == "Cap-d'Ail"
    assert canon_town("Eze") == "Èze"
    assert canon_town("st-jean-cap-ferrat") == "Saint-Jean-Cap-Ferrat"


def test_canon_town_from_postcode():
    assert canon_town(None, "06310") == "Beaulieu-sur-Mer"
    assert canon_town(None, "06300") == "Nice"
    assert canon_town("06450") == "Saint-Martin-Vésubie"  # tango passes a bare CP


# ------------------------------------------------------------- categories

@pytest.mark.parametrize("text,cat", [
    ("Vide-grenier des Gazelles", "brocante"),
    ("Brocante du Cours Saleya", "brocante"),
    ("Bourse des collectionneurs", "brocante"),
    ("Milonga de la Estación", "danse"),
    ("Practica et Milonga Jeudi c'est permis", "danse"),
    ("Sting", "autre"),                       # bare artist name — no signal
    ("Concert tremplin Nice Music Lab", "concert"),
    ("Chagall à l'œuvre — exposition", "expo"),
    ("Vernissage Africa Pop", "expo"),
    ("Visite guidée de la Crypte", "visite"),
    ("Atelier drapé", "atelier"),
    ("AI & Machine Learning Meetup", "business"),
    ("Startup networking afterwork", "business"),
    ("Language Exchange apéro", "social"),
    ("Fête traditionnelle du village", "marche"),
])
def test_classify(text, cat):
    assert classify(text) == cat


def test_classify_uses_all_context():
    # Title alone is meaningless; the type label saves it.
    assert classify("Sting", "Concert", "Théâtre de Verdure") == "concert"


# ------------------------------------------------------------- fingerprint

def _ev(**kw):
    base = dict(title="Brocante du Cours Saleya", start=date(2026, 7, 20),
                town="Nice", source="test")
    base.update(kw)
    return Event(**base)


def test_same_event_same_fingerprint_across_sources():
    a = _ev(source="brocabrac", venue="Cours Saleya, east end")
    b = _ev(source="explore_nca", venue="Cours Saleya", url="http://other")
    assert a.fingerprint == b.fingerprint


def test_fingerprint_ignores_accents_case_and_badges():
    a = _ev(title="Brocante du Cours Saleya")
    b = _ev(title="BROCANTE DU COURS SALEYA  (Gratuit)")
    assert a.fingerprint == b.fingerprint


def test_different_dates_differ():
    assert _ev(start=date(2026, 7, 20)).fingerprint != _ev(start=date(2026, 7, 27)).fingerprint


def test_different_towns_differ():
    assert _ev(town="Nice").fingerprint != _ev(town="Antibes").fingerprint


def test_end_before_start_is_dropped():
    assert _ev(start=date(2026, 7, 20), end=date(2026, 7, 1)).end is None


# ------------------------------------------------------------------- db

def test_upsert_dedups_and_merges(tmp_path):
    with db.connect(tmp_path / "t.db") as conn:
        added, merged = db.upsert(conn, [_ev(source="brocabrac", venue="Cours Saleya")])
        assert (added, merged) == (1, 0)

        # Same event, second source, richer venue + a note.
        added, merged = db.upsert(conn, [
            _ev(source="explore_nca", venue="Cours Saleya, partie Est", note="Every Monday")
        ])
        assert (added, merged) == (0, 1)

        rows = conn.execute("SELECT * FROM events").fetchall()
        assert len(rows) == 1
        assert rows[0]["venue"] == "Cours Saleya, partie Est"    # richer won
        assert rows[0]["note"] == "Every Monday"
        assert set(rows[0]["sources"].split(",")) == {"brocabrac", "explore_nca"}


def test_merge_never_nulls_a_field(tmp_path):
    with db.connect(tmp_path / "t.db") as conn:
        db.upsert(conn, [_ev(venue="Cours Saleya", note="Every Monday", url="http://a")])
        db.upsert(conn, [_ev(venue=None, note=None, url=None, source="other")])
        row = conn.execute("SELECT * FROM events").fetchone()
        assert row["venue"] == "Cours Saleya"
        assert row["note"] == "Every Monday"
        assert row["url"] == "http://a"


def test_first_seen_is_never_rewritten(tmp_path):
    """The email digest depends on this staying put."""
    with db.connect(tmp_path / "t.db") as conn:
        db.upsert(conn, [_ev()])
        first = conn.execute("SELECT first_seen FROM events").fetchone()["first_seen"]
        db.upsert(conn, [_ev(source="again", note="new info")])
        again = conn.execute("SELECT first_seen FROM events").fetchone()["first_seen"]
        assert first == again


def test_prune_past_keeps_multiday_still_running(tmp_path):
    with db.connect(tmp_path / "t.db") as conn:
        db.upsert(conn, [
            _ev(title="Old", start=date(2020, 1, 1)),
            _ev(title="Long expo", start=date(2020, 1, 1), end=date(2099, 1, 1)),
            _ev(title="Future", start=date(2099, 6, 1)),
        ])
        db.prune_past(conn)
        titles = {r["title"] for r in conn.execute("SELECT title FROM events")}
        assert titles == {"Long expo", "Future"}


def test_upcoming_excludes_pending_submissions(tmp_path):
    with db.connect(tmp_path / "t.db") as conn:
        db.upsert(conn, [
            _ev(title="Approved", start=date(2099, 1, 1)),
            _ev(title="Pending", start=date(2099, 1, 2), approved=False,
                submitted_by="someone@x.com"),
        ])
        assert {r["title"] for r in db.upcoming(conn)} == {"Approved"}
        assert len(db.upcoming(conn, include_pending=True)) == 2


# ---------------------------------------------------------------- build

def test_build_site(tmp_path):
    from niceevents.site import build
    with db.connect(tmp_path / "t.db") as conn:
        db.upsert(conn, [
            _ev(title="Brocante du Cours Saleya", start=date(2099, 7, 20)),
            _ev(title="Milonga de la Estación", start=date(2099, 7, 21),
                category="danse", outdoor=True),
        ])
        n, out = build(conn, out_dir=str(tmp_path / "dist"))
    assert n == 2
    html = (tmp_path / "dist" / "index.html").read_text(encoding="utf-8")
    assert "Milonga de la Estación" in html
    assert "What's" in html
    assert (tmp_path / "dist" / "events.json").exists()


# ------------------------------------------------------- title selection

def test_merge_prefers_readable_title_not_longest(tmp_path):
    """A SHOUTY title with a badge is longer but worse — length must not win."""
    with db.connect(tmp_path / "t.db") as conn:
        db.upsert(conn, [_ev(title="Brocante du Cours Saleya", source="brocabrac")])
        db.upsert(conn, [_ev(title="BROCANTE DU COURS SALEYA (Gratuit)", source="explore_nca")])
        row = conn.execute("SELECT title FROM events").fetchone()
        assert row["title"] == "Brocante du Cours Saleya"


def test_merge_title_order_independent(tmp_path):
    """Same outcome whichever source lands first."""
    with db.connect(tmp_path / "t.db") as conn:
        db.upsert(conn, [_ev(title="BROCANTE DU COURS SALEYA (Gratuit)", source="explore_nca")])
        db.upsert(conn, [_ev(title="Brocante du Cours Saleya", source="brocabrac")])
        row = conn.execute("SELECT title FROM events").fetchone()
        assert row["title"] == "Brocante du Cours Saleya"
