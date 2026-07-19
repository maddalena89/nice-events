"""OpenAgenda mapping + the national-dataset geo guard.

The API is national. The single most important behaviour here is that a
mislabelled or out-of-area record can never land on a Nice site — so the
postcode guard is tested hard.
"""
from __future__ import annotations

from datetime import date, timedelta

from niceevents.scrapers import REGISTRY
from niceevents.scrapers.openagenda import OpenAgenda, _iso_date, _iso_time


def _rec(**kw):
    base = {
        "title_fr": "Concert au Conservatoire",
        "firstdate_begin": "2099-07-18T20:30:00+02:00",
        "lastdate_end": "2099-07-18T22:30:00+02:00",
        "location_name": "Opéra de Nice",
        "location_city": "Nice",
        "location_postalcode": "06000",
        "location_department": "Alpes-Maritimes",
        "keywords_fr": ["musique", "classique"],
        "description_fr": "Une soirée de musique classique.",
        "canonicalurl": "https://openagenda.com/x/events/concert",
    }
    base.update(kw)
    return base


def _map(rec, today=date(2026, 7, 15)):
    return OpenAgenda.__new__(OpenAgenda)._to_event(rec, today)


def test_registered():
    assert "openagenda" in REGISTRY


def test_maps_a_culture_event():
    ev = _map(_rec())
    assert ev is not None
    assert ev.title == "Concert au Conservatoire"
    assert ev.town == "Nice"
    assert ev.venue == "Opéra de Nice"
    assert ev.time == "20:30"
    assert ev.source == "openagenda"
    assert ev.url.startswith("https://openagenda.com")


def test_non_06_postcode_is_dropped_even_if_department_says_otherwise():
    """A Paris record that slipped through the department filter must not show."""
    assert _map(_rec(location_postalcode="75001", location_city="Paris")) is None


def test_06_postcode_is_kept():
    assert _map(_rec(location_postalcode="06300", location_city="Nice")) is not None


def test_finished_events_dropped_running_ones_kept():
    today = date(2026, 7, 15)
    over = _rec(firstdate_begin="2026-07-01T20:00:00+02:00",
                lastdate_end="2026-07-10T22:00:00+02:00")
    assert _map(over, today) is None
    # A month-long exhibition that started in the past is still on.
    running = _rec(title_fr="Exposition Matisse",
                   firstdate_begin="2026-07-01T10:00:00+02:00",
                   lastdate_end="2026-08-30T18:00:00+02:00")
    ev = _map(running, today)
    assert ev is not None and ev.end is not None      # multi-day -> feeds the run badge


def test_missing_title_or_date_is_skipped_not_crashed():
    assert _map(_rec(title_fr="")) is None
    assert _map(_rec(firstdate_begin=None)) is None


def test_keywords_list_is_flattened_not_stringified():
    ev = _map(_rec(keywords_fr=["jazz", "festival"]))
    assert "['" not in (ev.note or "")     # not a raw Python list repr


def test_iso_helpers():
    assert _iso_date("2026-07-18T19:30:00+02:00") == date(2026, 7, 18)
    assert _iso_date(None) is None
    assert _iso_time("2026-07-18T19:30:00+02:00") == "19:30"
    assert _iso_time("2026-07-18T00:00:00+02:00") is None   # midnight -> no time
