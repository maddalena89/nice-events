"""A weekly series must not be listed as an every-day one.

explorenicecotedazur publishes "Club Sonore" as a single row from 2026-08-05 to
2026-09-24 with "Every Wednesday" in the description and no structured
recurrence at all. Nothing downstream read the sentence, so a 51-day span was
treated as 51 consecutive days and the feed put a Wednesday beach party on
Monday 7 September, directly above a Thursday one. A reader found it, which is
the wrong way round.

These tests pin both halves: reading the weekday out of the prose, and putting
the row on that weekday only.
"""
from datetime import date

from niceevents.models import weekly_weekdays
from niceevents.site import _first_slot, _mark_weekly


# ------------------------------------------------------------ reading the prose

def test_reads_english_and_french():
    assert weekly_weekdays("Every Wednesday, the beach comes alive") == [2]
    assert weekly_weekdays("Every Thursday night, Bocca Mar transforms") == [3]
    assert weekly_weekdays("Tous les mercredis à 18h") == [2]
    assert weekly_weekdays("chaque jeudi") == [3]


def test_reads_several_days():
    assert weekly_weekdays("every Monday, Wednesday and Friday") == [0, 2, 4]
    assert weekly_weekdays("chaque jeudi et vendredi") == [3, 4]


def test_looks_at_title_and_note_together():
    assert weekly_weekdays("Club Sonore", "Every Wednesday, the beach…") == [2]


def test_needs_an_explicit_recurrence_word():
    """A day name on its own is not a recurrence, or half the feed would be one."""
    assert weekly_weekdays("Book by Friday") == []
    assert weekly_weekdays("closed on Mondays") == []
    assert weekly_weekdays("Le mercredi soir") == []
    assert weekly_weekdays("Toutes les semaines") == []
    assert weekly_weekdays(None) == []


# ------------------------------------------------------------------- the tagging

def _club_sonore():
    return {"title": "Club Sonore", "start": "2026-08-05", "end": "2026-09-24",
            "note": "Every Wednesday, the beach comes alive with the parties."}


def test_marks_a_long_span_with_its_weekday():
    events = [_club_sonore()]
    _mark_weekly(events)
    assert events[0]["days"] == [2]


def test_leaves_a_short_span_alone():
    """"Every Saturday" on a two-day row is describing the series, not this row."""
    events = [{"title": "Fête", "start": "2026-08-05", "end": "2026-08-06",
               "note": "Every Saturday in summer"}]
    _mark_weekly(events)
    assert "days" not in events[0]


def test_leaves_a_single_day_event_alone():
    events = [{"title": "Concert", "start": "2026-08-05", "end": None,
               "note": "Every Wednesday in August"}]
    _mark_weekly(events)
    assert "days" not in events[0]


def test_leaves_an_ordinary_run_untagged():
    """No recurrence in the text means no `days`, so nothing about it changes."""
    events = [{"title": "Exposition", "start": "2026-08-05", "end": "2026-09-24",
               "note": "Une exposition de peinture contemporaine."}]
    _mark_weekly(events)
    assert "days" not in events[0]


# --------------------------------------------------------------- the placement

def test_skips_forward_to_the_right_weekday():
    """The bug, exactly: asked about Monday 7 Sep, a Wednesday event says Wednesday."""
    e = _club_sonore()
    _mark_weekly([e])
    assert _first_slot(e, "2026-09-07", "2026-09-14") == "2026-09-09"


def test_lands_on_the_day_itself_when_asked_on_that_day():
    e = _club_sonore()
    _mark_weekly([e])
    assert _first_slot(e, "2026-09-09", "2026-09-16") == "2026-09-09"


def test_returns_nothing_when_the_range_holds_no_matching_day():
    e = _club_sonore()
    _mark_weekly([e])
    # Thursday to Saturday contains no Wednesday.
    assert _first_slot(e, "2026-09-10", "2026-09-12") is None


def test_never_runs_past_the_end_of_the_series():
    e = _club_sonore()
    _mark_weekly([e])
    # The series ends Thu 24 Sep; the last Wednesday is the 23rd.
    assert _first_slot(e, "2026-09-24", "2026-10-31") is None


def test_an_untagged_event_is_placed_exactly_as_before():
    e = {"title": "Exposition", "start": "2026-08-05", "end": "2026-09-24"}
    assert _first_slot(e, "2026-09-07", "2026-09-14") == "2026-09-07"
    assert _first_slot({"start": "2026-09-10"}, "2026-09-07", "2026-09-14") == "2026-09-10"


def test_both_reported_events_land_on_their_own_weekday():
    """The two rows in the 7 Sep report, end to end."""
    events = [
        _club_sonore(),
        {"title": "Soirées Obrigado à Bocca Mar !", "start": "2026-08-06",
         "end": "2026-09-24",
         "note": "Every Thursday night, Bocca Mar switches to OBRIGADO mode!"},
    ]
    _mark_weekly(events)
    slots = [_first_slot(e, "2026-09-07", "2026-09-14") for e in events]
    assert slots == ["2026-09-09", "2026-09-10"]
    assert [date.fromisoformat(s).strftime("%A") for s in slots] \
        == ["Wednesday", "Thursday"]
