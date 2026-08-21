"""A source that says "(ANNULEE)" must not be advertised as on.

6 August 2026: the Casita milonga was cancelled, the reference tango agenda said
so in the event title, and the site still showed the night as going ahead.
"""
from __future__ import annotations

from datetime import date

import pytest

from niceevents.cancellations import mark_cancelled
from niceevents.models import Event


def _one(title, **kw):
    return mark_cancelled([{"title": title, "town": "Nice", "start": "2026-08-06", **kw}])[0]


def _fp(title: str) -> str:
    return Event(title=title, start=date(2026, 8, 6), town="Nice", source="t").fingerprint


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


# ------------------------------------------------- the marker and the identity
#
# Flagging the cancelled row is only half the job. A calendar RETITLES rather
# than deletes, so the cancelled entry and the original are the same event and
# must share a fingerprint. If they do not, the cancelled one lands as a second
# row and the original stays in the feed, advertised as on, right next to the
# struck-through one. That is what actually happened on 2026-08-06: three layers
# were looking for the cancellation and the fourth, dedup, quietly undid them.

@pytest.mark.parametrize("marked", [
    "(ANNULEE) MILONGA de la Casita",       # what the tango agenda really writes
    "(ANNULÉE) MILONGA de la Casita",
    "ANNULEE MILONGA de la Casita",
    "Annulée - MILONGA de la Casita",
    "annulés MILONGA de la Casita",
    "CANCELLED: MILONGA de la Casita",
])
def test_a_cancelled_title_fingerprints_as_the_same_event(marked):
    assert _fp(marked) == _fp("MILONGA de la Casita")


def test_the_marker_does_not_collapse_two_different_events():
    assert _fp("(ANNULEE) MILONGA de la Casita") != _fp("MILONGA de la Estacion")


def test_the_stem_is_deliberately_broad():
    # `annul\w*` also swallows French words that merely begin the same way, so
    # "Expo Annulaire" keys as "Expo". That is a conscious trade: the cost is two
    # unrelated events merging, which is rare and visible; the cost of being
    # narrower is missing a real cancellation, which is invisible and sends
    # somebody to a closed door. cancellations.py made the same call, and the two
    # must agree or the marker gets flagged in one place and kept in the other.
    assert _fp("Expo Annulaire") == _fp("Expo")


# --------------------------------------------------------------- the merge step
#
# 21 August 2026. harvest resolved the RECURRENCE-ID overrides correctly and
# yielded both Casita nights with "(ANNULÉE)" in the title, and the site still
# advertised both as on. The marker was thrown away one layer further down, by
# the title merge in db.upsert: _better_title scores titles for readability, and
# a cancellation retitle loses that contest. Two different ways, which is why
# raising the caps threshold alone would not have fixed it.

from niceevents.db import _better_title


def test_a_shouted_cancellation_beats_a_tidy_live_title():
    """75% caps, so the SHOUTING rule scored it +10 and the clean title won."""
    assert _better_title(
        "(ANNULÉE) MILONGA DE L'AMITIE à la Casita",
        "Milonga de L'AMITIE à la Casita",
    ).startswith("(ANNULÉE)")


def test_a_cancellation_that_ties_still_beats_the_incumbent():
    """Both score 0, and on a tie the incumbent wins. The 27 Aug Casita."""
    assert _better_title(
        '(ANNULÉE) MILONGA précédée d\'une Pràctica "Jeudi c\'est permis !" à la Casita',
        'MILONGA précédée d\'une Pràctica "Jeudi c\'est permis !" à la Casita',
    ).startswith("(ANNULÉE)")


def test_dropping_the_marker_is_not_forced():
    """A calendar removing (ANNULÉE) means the night is back on. Leaving a live
    event struck through is the same harm as advertising a cancelled one, so
    this direction falls through to ordinary scoring."""
    assert _better_title(
        "Milonga de L'AMITIE à la Casita",
        "(ANNULÉE) MILONGA DE L'AMITIE à la Casita",
    ) == "Milonga de L'AMITIE à la Casita"


def test_readability_scoring_still_applies_when_neither_is_cancelled():
    assert _better_title(
        "BROCANTE DU COURS SALEYA (Gratuit)", "Brocante du Cours Saleya"
    ) == "Brocante du Cours Saleya"


# --------------------------------------------------- the hand-maintained list
#
# The list is written by a person reading a poster, who types "milonga de l
# amitie", not "milonga de l'amitie". Matching on the folded title kept the
# apostrophe, so such a line never matched anything and looked like it worked.
# The 25 July 2026 entry had been dead on arrival.

from niceevents.cancellations import CANCELLED, mark_cancelled as mc


def _row(title, town="Nice", start="2026-08-22"):
    return {"title": title, "town": town, "start": start}


def test_a_needle_written_without_apostrophes_matches():
    got = mc([_row("Milonga de L'AMITIE à la Casita")])[0]
    assert got["cancelled"] is True


def test_the_list_still_needs_the_right_town_and_date():
    assert "cancelled" not in mc([_row("Milonga de L'AMITIE à la Casita", town="Cannes")])[0]
    assert "cancelled" not in mc([_row("Milonga de L'AMITIE à la Casita", start="2026-09-26")])[0]


def test_a_later_repeat_of_a_cancelled_series_stays_live():
    """Only the named date is off. 3 Sept is the same weekly milonga, still on."""
    t = 'MILONGA précédée d\'une Pràctica "Jeudi c\'est permis !" à la Casita'
    assert mc([_row(t, start="2026-08-27")])[0]["cancelled"] is True
    assert "cancelled" not in mc([_row(t, start="2026-09-03")])[0]


def test_every_line_in_the_list_is_reachable():
    """A needle that matches nothing is a typo, and a silent one. Assert each
    line can still match the title it was written for."""
    from niceevents.cancellations import _loose
    for needle, town, cdate, _note in CANCELLED:
        assert _loose(needle), f"empty needle for {town} {cdate}"
        assert _loose(needle) in _loose(f"prefix {needle} suffix"), needle
