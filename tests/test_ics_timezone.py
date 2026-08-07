"""A UTC start time must be published as Nice local time.

Google Calendar writes a ONE-OFF event in UTC ("DTSTART:20260904T180000Z") and a
RECURRING series in a named zone ("DTSTART;TZID=Europe/Paris:20260903T200000").
Both scrapers throw the TZID parameter away while parsing, so the trailing Z is
the only thing left that says "this still needs converting".

Neither of them looked at it. On 2026-08-07 the live site had 21 verified La
Zonmé gigs advertised early: doors at 20:00 published as 18:00. The offset was
exactly two hours before 25 October and exactly one hour after, which is
European daylight saving to the day, and is how the bug was identified.

The two months below are chosen for that reason: September is UTC+2 in Paris,
December is UTC+1. A fix that hard-codes a single offset passes one and fails
the other.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from niceevents.scrapers.gcal import parse_dt
from niceevents.scrapers.harvest import (VenueHarvest, _events_from_ics, _ics_dt,
                                         _ics_starts, _ics_time)

FEED = "Agenda Tango Argentin Nice Riviera 06"


# --------------------------------------------------------------- the raw parse

@pytest.mark.parametrize("parse", [_ics_dt, parse_dt])
class TestBothParsers:
    """harvest and gcal had the identical defect, so they get the identical test."""

    def test_summer_utc_start_gains_two_hours(self, parse):
        # The real one: Tolbians at La Zonmé, doors 20:00 Nice time.
        assert parse("20260904T180000Z") == (date(2026, 9, 4), "20:00")

    def test_winter_utc_start_gains_one_hour(self, parse):
        assert parse("20261207T190000Z") == (date(2026, 12, 7), "20:00")

    def test_the_day_daylight_saving_ends(self, parse):
        # 25 October 2026 is the last Sunday of October: Paris drops to UTC+1.
        assert parse("20261024T180000Z") == (date(2026, 10, 24), "20:00")
        assert parse("20261026T190000Z") == (date(2026, 10, 26), "20:00")

    def test_a_zoned_value_is_already_local_and_is_left_alone(self, parse):
        # split_prop/_ics_prop has stripped ";TZID=Europe/Paris" by now, so this
        # arrives bare. No Z means no conversion.
        assert parse("20260903T200000") == (date(2026, 9, 3), "20:00")

    def test_converting_can_roll_the_date(self, parse):
        # A milonga starting 23:30 UTC is 01:30 the NEXT morning here. The date
        # and the time have to move together or they end up in different zones.
        assert parse("20260904T233000Z") == (date(2026, 9, 5), "01:30")

    def test_an_all_day_entry_still_has_no_time(self, parse):
        assert parse("20260904") == (date(2026, 9, 4), None)

    def test_midnight_still_means_no_time_given(self, parse):
        # Local midnight is these calendars' way of saying "time unknown".
        assert parse("20260904T000000") == (date(2026, 9, 4), None)

    def test_seconds_are_tolerated_and_junk_is_not(self, parse):
        assert parse("20260904T180000Z")[1] == "20:00"
        assert parse("not a date") == (None, None)


def test_ics_time_wrapper_converts_too():
    # Kept as a wrapper so existing callers pick the fix up for free.
    assert _ics_time("20260904T180000Z") == "20:00"
    assert _ics_time("20260903T200000") == "20:00"


# ------------------------------------------------------- through the fan-out

def test_a_recurring_utc_series_keeps_its_z():
    """The bug's back door: materialising an RRULE rebuilds the DTSTART string.

    Drop the Z while doing that and every occurrence looks local again, so the
    series is published early even though the parse above is correct.
    """
    today = date(2026, 9, 1)
    raw = {"DTSTART": "20260903T180000Z", "RRULE": "FREQ=WEEKLY;COUNT=3"}
    starts = _ics_starts(raw, today)
    assert starts, "the series produced no occurrences"
    assert all(s.endswith("Z") for s in starts), starts
    assert all(_ics_dt(s)[1] == "20:00" for s in starts), starts


def test_a_recurring_zoned_series_is_unchanged():
    today = date(2026, 9, 1)
    raw = {"DTSTART": "20260903T200000", "RRULE": "FREQ=WEEKLY;COUNT=3"}
    starts = _ics_starts(raw, today)
    assert starts
    assert not any(s.endswith("Z") for s in starts)
    assert all(_ics_dt(s)[1] == "20:00" for s in starts), starts


# ------------------------------------------------------- end to end, one event

def _harvested(dtstart: str, dtend: str | None = None):
    ics = ["BEGIN:VCALENDAR", "BEGIN:VEVENT", f"DTSTART:{dtstart}"]
    if dtend:
        ics.append(f"DTEND:{dtend}")
    ics += ["SUMMARY:Tolbians",
            "LOCATION:La Zonme\\, 2 Rue Trachel\\, 06000 Nice\\, France",
            "END:VEVENT", "END:VCALENDAR"]
    raw = next(_events_from_ics("\n".join(ics) + "\n"))
    return VenueHarvest()._from_ics(raw, FEED, date.today(), "Nice")


def test_the_published_event_carries_the_local_time():
    soon = date.today() + timedelta(days=30)
    e = _harvested(f"{soon:%Y%m%d}T180000Z")
    # Not asserting a literal here: the offset depends on where `soon` lands
    # relative to the clock change. Asserting it matches the parser keeps this
    # honest all year round.
    assert e.time == _ics_dt(f"{soon:%Y%m%d}T180000Z")[1]
    assert e.time != "18:00"


def test_a_night_that_runs_past_midnight_is_not_a_two_day_event():
    soon = date.today() + timedelta(days=30)
    e = _harvested(f"{soon:%Y%m%d}T180000Z", f"{soon:%Y%m%d}T233000Z")
    assert not e.is_multiday, (e.start, e.end)
