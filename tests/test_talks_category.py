"""Talks are not business, and a fixed rule has to reach rows already stored.

Both halves were real bugs. In French a "conférence" is a public lecture, and
the classifier read the word as a business term, which put 76 of 110 events in
"Business, tech & AI" wrongly — museum talks, an archaeology lecture, a Ray
Charles appreciation. Correcting the rule then fixed nothing that was already in
the database, because the stored category was never refreshed on a re-scrape.
"""
from datetime import date

from niceevents import db
from niceevents.models import (
    DISPLAY_CATEGORIES, Event, category_from_type, classify,
)


# --- a conférence is a talk ------------------------------------------------

def test_french_lectures_are_not_business():
    for title in [
        "Conférence - Église Saint Barthélémy",
        'Conférence “Sappho: Une parole au présent” à la Villa Kérylos',
        "Micro-conférence : Des préhistoriques à la plage !",
    ]:
        assert classify(title) == "atelier", title


def test_a_commercial_conference_is_still_business():
    """The words that actually mean business are tested before the word that
    merely means "a talk", so this must not regress."""
    for title in [
        "Conférence startup : lever des fonds",
        "Tech conference Nice",
        "Conférence entrepreneur & networking",
        "AI conference",
    ]:
        assert classify(title) == "business", title


def test_the_source_type_label_agrees():
    assert category_from_type("Conférence") == "atelier"
    assert category_from_type("Conference") == "atelier"
    assert category_from_type("Atelier") == "atelier"


def test_talks_and_workshops_share_one_chip():
    assert DISPLAY_CATEGORIES["atelier"] == "Talks & workshops"
    # The grid holds 12 boxes: the categories plus "All the events". A 13th
    # leaves a ragged row, which is why talks were folded in rather than given
    # a chip of their own.
    assert len(DISPLAY_CATEGORIES) + 1 == 12


def test_the_url_slug_did_not_move():
    """Renaming a chip must not move a page search engines have indexed."""
    from niceevents.landing import CAT_SLUG
    assert CAT_SLUG["atelier"] == "workshops"


# --- the stored category has to be correctable -----------------------------

def _ev(**kw):
    d = dict(title="A talk about archives", start=date(2026, 9, 19),
             town="Nice", venue="Musée", category="business",
             url="https://example.com/1", source="nice_fr")
    d.update(kw)
    return Event(**d)


def test_rescraping_corrects_a_stale_category(tmp_path):
    """The whole point: fixing a rule must reach rows already in the table."""
    with db.connect(tmp_path / "t.db") as conn:
        db.upsert(conn, [_ev(category="business")])
        stored = conn.execute("SELECT category FROM events").fetchone()[0]
        assert stored == "business"

        # same event, same source, now classified correctly
        db.upsert(conn, [_ev(category="atelier")])
        stored = conn.execute("SELECT category FROM events").fetchone()[0]
        assert stored == "atelier", "a re-scrape must be able to reclassify"


def test_another_source_cannot_reclassify_someone_elses_row(tmp_path):
    """Only the source that owns the row may change its category, or two sources
    that disagree would flip it back and forth every morning."""
    with db.connect(tmp_path / "t.db") as conn:
        db.upsert(conn, [_ev(category="atelier", source="nice_fr")])
        db.upsert(conn, [_ev(category="concert", source="openagenda")])
        stored = conn.execute("SELECT category FROM events").fetchone()[0]
        assert stored == "atelier"
