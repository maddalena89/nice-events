"""Harvester additions for the dance feeds: address parsing + RRULE expansion."""
from __future__ import annotations

from datetime import date

from niceevents.scrapers.harvest import (
    VenueHarvest, _events_from_ics, _ics_starts, _split_ics_location,
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
