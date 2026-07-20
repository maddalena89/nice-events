"""Harvester additions for the dance feeds: address parsing + RRULE expansion."""
from __future__ import annotations

from datetime import date

from niceevents.scrapers.harvest import (
    VenueHarvest, _events_from_ics, _ics_starts, _in_scope, _split_ics_location,
)

H = VenueHarvest.__new__(VenueHarvest)
TODAY = date(2026, 7, 15)


# --------------------------------------------------------- LOCATION parsing
def test_location_pulls_town_and_postcode():
    assert _split_ics_location("5 Rue Jacques Leonetti 06160 Juan-les-Pins") == (
        "5 Rue Jacques Leonetti", "Juan-les-Pins", "06160")
    assert _split_ics_location("1715 route de Nice, 06600 Antibes") == (
        "1715 route de Nice", "Antibes", "06600")


def test_location_without_postcode_is_all_venue():
    assert _split_ics_location("Cave Romagnan, Nice") == ("Cave Romagnan, Nice", None, None)


def test_location_reads_non_06_french_postcode():
    _, city, pc = _split_ics_location("Promenade du Peyrou, 34000 Montpellier, France")
    assert (city, pc) == ("Montpellier", "34000")


# --------------------------------------------------- 06-only scope gate
def test_scope_keeps_06_drops_elsewhere_and_foreign():
    assert _in_scope("Nice", "06000", "12 rue X 06000 Nice") is True
    assert _in_scope("Montpellier", "34000", "... 34000 Montpellier") is False
    assert _in_scope("Mont-Dore", "63240", "... 63240 Mont-Dore") is False
    assert _in_scope(None, None, "Herräng, 763 71 Herräng, Suède") is False
    # No address at all: a local feed's practice — let the default town place it.
    assert _in_scope(None, None, "") is True


def test_from_ics_drops_out_of_area_event():
    ics = """BEGIN:VCALENDAR
BEGIN:VEVENT
SUMMARY:Swingin' Montpellier
DTSTART:20260722T200000
LOCATION:Promenade du Peyrou, Rue la Blottière, 34000 Montpellier, France
END:VEVENT
END:VCALENDAR"""
    (o,) = list(_events_from_ics(ics))
    assert H._from_ics(o, "Swingin'Nice", TODAY, "Nice") is None


# --------------------------------------------------------- real salsa feed
SALSA_ICS = """BEGIN:VCALENDAR
BEGIN:VEVENT
UID:evt46093@salsa.faurax.fr
DTSTART;TZID=Europe/Paris:20260721T200000
DTEND;TZID=Europe/Paris:20260721T235959
SUMMARY:Salsa Wag Nights - 100% Salsa
LOCATION:5 Rue Jacques Leonetti 06160 Juan-les-Pins
URL:https://salsa.faurax.fr/index.php/evt/20260721-46093
END:VEVENT
BEGIN:VEVENT
UID:evtnice@salsa.faurax.fr
DTSTART;TZID=Europe/Paris:20260724T203000
DTEND;TZID=Europe/Paris:20260724T235959
SUMMARY:Les voûtes soirée latine
LOCATION:12 Rue Jules Gilly 06300 Nice
END:VEVENT
END:VCALENDAR"""


def test_salsa_feed_maps_town_and_category():
    evs = list(_events_from_ics(SALSA_ICS))
    wag = H._from_ics(evs[0], "Liste Salsa d'Olivier", TODAY)
    assert wag.time == "20:00"
    assert wag.category == "danse"                 # salsa -> dance
    assert wag.town != "Unknown"                   # town came from the address
    nice = H._from_ics(evs[1], "Liste Salsa d'Olivier", TODAY)
    assert nice.town == "Nice"
    assert nice.category == "danse"


# --------------------------------------------------------- RRULE expansion
def _raw(ics: str) -> dict:
    return list(_events_from_ics(ics))[0]


def test_weekly_rrule_materialises_upcoming_tuesdays():
    ics = """BEGIN:VCALENDAR
BEGIN:VEVENT
SUMMARY:Lindy practice
DTSTART;TZID=Europe/Paris:20240102T193000
RRULE:FREQ=WEEKLY;BYDAY=TU
LOCATION:La Zonmé 06000 Nice
END:VEVENT
END:VCALENDAR"""
    starts = _ics_starts(_raw(ics), TODAY)
    assert starts, "a weekly series must produce upcoming dates"
    dates = [date(int(s[:4]), int(s[4:6]), int(s[6:8])) for s in starts]
    assert all(d >= TODAY for d in dates)
    assert all(d.weekday() == 1 for d in dates)    # every one is a Tuesday
    assert dates[0] == date(2026, 7, 21)           # first Tuesday on/after 15 Jul
    assert all(s.endswith("T193000") for s in starts)   # time carried over


def test_monthly_last_thursday_rrule():
    ics = """BEGIN:VCALENDAR
BEGIN:VEVENT
SUMMARY:So Blue So Dance
DTSTART;TZID=Europe/Paris:20240104T200000
RRULE:FREQ=MONTHLY;BYDAY=-1TH
LOCATION:1715 Route de Nice 06600 Antibes
END:VEVENT
END:VCALENDAR"""
    starts = _ics_starts(_raw(ics), TODAY)
    dates = [date(int(s[:4]), int(s[4:6]), int(s[6:8])) for s in starts]
    assert date(2026, 7, 30) in dates              # last Thursday of Jul 2026
    for d in dates:
        assert d.weekday() == 3                     # Thursday
        # it's the last Thursday: +7 days lands in the next month
        from datetime import timedelta
        assert (d + timedelta(days=7)).month != d.month


def test_no_rrule_returns_single_start():
    ics = """BEGIN:VCALENDAR
BEGIN:VEVENT
SUMMARY:One off
DTSTART:20260801T210000
END:VEVENT
END:VCALENDAR"""
    assert _ics_starts(_raw(ics), TODAY) == ["20260801T210000"]
