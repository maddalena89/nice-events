"""The Agenda Tango Argentin Nice Riviera 06, read through the harvest engine.

Fixture lines are copied verbatim from the real feed, including the escaped
commas iCal uses and the address styles this particular calendar writes by hand.
"""
from __future__ import annotations

from datetime import date, timedelta

from niceevents.cancellations import mark_cancelled
from niceevents.scrapers.harvest import VenueHarvest, _events_from_ics, _town_from_text

FEED = "Agenda Tango Argentin Nice Riviera 06"
SOON = date.today() + timedelta(days=7)


def _ics(summary: str, location: str) -> str:
    return (
        "BEGIN:VCALENDAR\n"
        "BEGIN:VEVENT\n"
        f"DTSTART;VALUE=DATE:{SOON:%Y%m%d}\n"
        f"SUMMARY:{summary}\n"
        f"LOCATION:{location}\n"
        "END:VEVENT\n"
        "END:VCALENDAR\n"
    )


def _event(summary: str, location: str):
    raw = next(_events_from_ics(_ics(summary, location)))
    return VenueHarvest()._from_ics(raw, FEED, date.today(), "Nice")


# ------------------------------------------------------------------- towns

def test_postcode_gives_the_town():
    e = _event("MILONGA de l'Amitie",
               "La Casita\\, 8 Rue Gaston Charbonnier\\, 06300 Nice\\, France")
    assert e.town == "Nice"
    assert "Casita" in e.venue


def test_cannes_and_antibes_are_not_forced_to_nice():
    assert _event("MILONGA de la Liberte",
                  "Kiosque a musique des Allees de la Liberte 06400 CANNES").town == "Cannes"
    assert _event("MILONGA Le Bandoneon",
                  "Route de Grasse\\, 2139 Domaine des grives 06600 ANTIBES").town == "Antibes"


def test_town_read_from_the_text_when_there_is_no_postcode():
    # "06" is the department, not a postcode: the commune is spelled out instead.
    assert _event("MILONGA BICILONGA", "12ter Place Garibaldi 06 NICE").town == "Nice"


def test_feed_name_never_becomes_the_town():
    # The feed is called "…Nice Riviera 06". Before this, a location with no
    # postcode fell back to the feed name and put that string in the town column.
    e = _event("MILONGA quelque part", "Salle sans adresse")
    assert e.town == "Nice"
    assert "Riviera" not in e.town


def test_longest_commune_wins():
    assert _town_from_text("Salle des fetes 06 SAINT-JEAN-CAP-FERRAT") == "Saint-Jean-Cap-Ferrat"


def test_a_town_outside_the_06_is_dropped():
    assert _event("MILONGA", "Salle Rouge 34000 MONTPELLIER") is None


# ------------------------------------------------------------- cancellation

def test_cancelled_milonga_is_flagged_not_advertised():
    # The 6 August 2026 case, in the shape the feed actually publishes it.
    e = _event('(ANNULEE) MILONGA precedee d\'une Practica "Jeudi c\'est permis !" a la Casita',
               "La Casita\\, 8 Rue Gaston Charbonnier\\, 06300 Nice\\, France")
    d = mark_cancelled([{"title": e.title, "town": e.town, "start": e.start.isoformat()}])[0]
    assert d["cancelled"] is True
    assert d["title"].startswith("MILONGA")


def test_recurrence_override_cancels_the_date_it_names():
    """The 18 August 2026 case: the cancellation is written AFTER the series.

    Google cancels one night of a weekly milonga by appending a replacement
    VEVENT with a RECURRENCE-ID and an "(ANNULEE)" title. The series keeps its
    RRULE, its clean title and NO EXDATE, so both reach the scraper for the same
    night and — because _title_key strips "annulee" — they fingerprint the same.
    First-wins kept the clean one and the site advertised a cancelled milonga.
    """
    weekly = SOON + timedelta(days=7)      # inside the horizon, and a 2nd occurrence
    feed = (
        "BEGIN:VCALENDAR\n"
        # the series, written first, clean title, no EXDATE for the cancelled date
        "BEGIN:VEVENT\n"
        "UID:casita\n"
        f"DTSTART;VALUE=DATE:{SOON:%Y%m%d}\n"
        f"RRULE:FREQ=WEEKLY;BYDAY={'MO TU WE TH FR SA SU'.split()[SOON.weekday()]}\n"
        "SUMMARY:MILONGA a la Casita\n"
        "LOCATION:La Casita\\, 8 Rue Gaston Charbonnier\\, 06300 Nice\\, France\n"
        "END:VEVENT\n"
        # the cancellation, appended at the bottom, as the real calendar writes it
        "BEGIN:VEVENT\n"
        "UID:casita\n"
        f"RECURRENCE-ID;VALUE=DATE:{SOON:%Y%m%d}\n"
        f"DTSTART;VALUE=DATE:{SOON:%Y%m%d}\n"
        "SUMMARY:(ANNULEE) MILONGA a la Casita\n"
        "LOCATION:La Casita\\, 8 Rue Gaston Charbonnier\\, 06300 Nice\\, France\n"
        "END:VEVENT\n"
        "END:VCALENDAR\n"
    )

    h = VenueHarvest()
    h.get = lambda url: type("R", (), {"text": feed})()
    events = list(h._one(FEED, "x", "ics", date.today(), set(), "Nice"))

    by_date = {e.start: e for e in events}
    assert SOON in by_date, "the cancelled night must stay listed, not vanish"

    cancelled = mark_cancelled([{"title": by_date[SOON].title, "town": "Nice",
                                 "start": SOON.isoformat()}])[0]
    assert cancelled["cancelled"] is True
    assert cancelled["title"].startswith("MILONGA")

    # The override replaces exactly one night. The rest of the series is untouched.
    assert len([e for e in events if e.start == SOON]) == 1
    if weekly in by_date:
        assert not by_date[weekly].title.upper().startswith("(ANNUL")


def test_category_is_dance():
    e = _event("MILONGA de la Estacion", "35\\, avenue Malaussena - 06000 NICE")
    assert e.category == "danse"


def test_all_day_entries_carry_no_invented_time():
    e = _event("MILONGA LA LOCA", "Arty Studio\\, 25 bis Rue Gubernatis - 06000 NICE")
    assert e.time is None
