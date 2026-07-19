"""Venue harvester — the JSON-LD and iCal parsers.

The engine is what's tested here (not specific venues): if these parsers are
correct, adding a venue is genuinely just a URL in VENUES.
"""
from __future__ import annotations

from datetime import date

from niceevents.scrapers import REGISTRY
from niceevents.scrapers.harvest import (
    VenueHarvest, _events_from_ics, _events_from_jsonld, _ics_date, _ics_time,
    _unfold_ics,
)

H = VenueHarvest.__new__(VenueHarvest)
TODAY = date(2026, 7, 15)


def test_registered():
    assert "harvest" in REGISTRY


# ---------------------------------------------------------------- JSON-LD
JSONLD_PAGE = """
<html><head>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"TheaterEvent",
 "name":"Cyrano de Bergerac","startDate":"2026-07-20T20:30:00+02:00",
 "endDate":"2026-07-20T22:30:00+02:00","url":"https://tnn.fr/cyrano",
 "description":"Une reprise du classique.",
 "location":{"@type":"Place","name":"Théâtre National de Nice",
   "address":{"@type":"PostalAddress","addressLocality":"Nice","postalCode":"06300"}}}
</script>
</head><body>…</body></html>"""


def test_jsonld_single_event():
    (o,) = list(_events_from_jsonld(JSONLD_PAGE))
    ev = H._from_jsonld(o, "TNN", TODAY)
    assert ev.title == "Cyrano de Bergerac"
    assert ev.start.isoformat() == "2026-07-20"
    assert ev.time == "20:30"
    assert ev.town == "Nice"
    assert ev.venue == "Théâtre National de Nice"
    assert ev.category == "scene"          # theatre -> stage
    assert ev.source == "harvest"


def test_jsonld_graph_and_array_and_subtypes():
    page = """<script type="application/ld+json">
    {"@graph":[
      {"@type":"MusicEvent","name":"Jazz Night","startDate":"2026-08-01",
       "location":{"name":"Opéra","address":{"postalCode":"06000"}}},
      {"@type":"Organization","name":"not an event"},
      {"@type":["Festival","Event"],"name":"Fest","startDate":"2026-08-02",
       "location":"Cimiez"}
    ]}</script>"""
    names = sorted(o.get("name") for o in _events_from_jsonld(page))
    assert names == ["Fest", "Jazz Night"]      # the Organization is excluded


def test_jsonld_past_event_dropped():
    page = """<script type="application/ld+json">
    {"@type":"Event","name":"Old","startDate":"2026-01-01",
     "location":{"address":{"postalCode":"06000"}}}</script>"""
    (o,) = list(_events_from_jsonld(page))
    assert H._from_jsonld(o, "V", TODAY) is None


# ------------------------------------------------------------------- iCal
ICS = """BEGIN:VCALENDAR
BEGIN:VEVENT
SUMMARY:Soirée slam
DTSTART;TZID=Europe/Paris:20260722T193000
DTEND;TZID=Europe/Paris:20260722T220000
LOCATION:Cave Romagnan\\, Nice
URL:https://example.org/slam
DESCRIPTION:Scène ouverte\\nvenez nombreux
END:VEVENT
BEGIN:VEVENT
SUMMARY:Expo photo
DTSTART:20260701
DTEND:20260830
LOCATION:Galerie
END:VEVENT
END:VCALENDAR"""


def test_ics_parses_events():
    evs = list(_events_from_ics(ICS))
    assert len(evs) == 2
    slam = H._from_ics(evs[0], "Cave Romagnan", TODAY)
    assert slam.title == "Soirée slam"
    assert slam.time == "19:30"
    assert slam.venue == "Cave Romagnan, Nice"     # escaped comma unescaped
    assert "venez nombreux" in slam.note


def test_ics_multiday_expo_keeps_end():
    evs = list(_events_from_ics(ICS))
    expo = H._from_ics(evs[1], "Galerie", TODAY)
    assert expo.end is not None and expo.end != expo.start   # feeds the run badge


def test_ics_all_day_has_no_time():
    assert _ics_time("20260701") is None
    assert _ics_time("20260722T193000") == "19:30"
    assert _ics_time("20260722T000000") is None      # midnight = no time


def test_ics_line_unfolding():
    folded = "SUMMARY:Very long\n  title here\nDTSTART:20260722"
    lines = _unfold_ics(folded)
    assert lines[0] == "SUMMARY:Very long title here"


def test_ics_date_bad_value():
    assert _ics_date("garbage") is None
    assert _ics_date("20260722T193000") == date(2026, 7, 22)
