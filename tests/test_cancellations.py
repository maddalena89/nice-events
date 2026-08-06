"""A source that says "(ANNULEE)" must not be advertised as on.

6 August 2026: the Casita milonga was cancelled, the reference tango agenda said
so in the event title, and the site still showed the night as going ahead.
"""
from __future__ import annotations

from niceevents.cancellations import mark_cancelled


def _one(title, **kw):
    return mark_cancelled([{"title": title, "town": "Nice", "start": "2026-08-06", **kw}])[0]


def test_the_real_one():
    e = _one('(ANNULEE) MILONGA précédée d\'une Pràctica "Jeudi c\'est permis !" à la Casita')
    assert e["cancelled"] is True
    assert e["cancel_note"] == "Annulé"
    assert e["title"].startswith("MILONGA")      # marker lifted, title still readable


def test_accents_and_case_and_english():
    for t in ("(ANNULÉE) Milonga", "Annulé - Concert", "[annulée] Bal", "CANCELLED: Gig"):
        assert _one(t)["cancelled"] is True, t


def test_a_live_event_is_untouched():
    e = _one("MILONGA de la Estacion")
    assert "cancelled" not in e
    assert e["title"] == "MILONGA de la Estacion"


def test_refund_boilerplate_in_the_note_is_not_a_cancellation():
    # Title only. Descriptions are full of "en cas d'annulation, remboursement".
    e = _one("Concert au Kiosque", note="En cas d'annulation, remboursement sous 8 jours")
    assert "cancelled" not in e


def test_a_title_that_is_only_the_marker_keeps_something_to_show():
    assert _one("Annulée")["title"]               # never blank


def test_manual_list_still_works():
    e = mark_cancelled([{"title": "Milonguita de la Casita", "town": "Nice",
                         "start": "2026-08-02"}])[0]
    assert e["cancelled"] is True
