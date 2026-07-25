"""Phantom / dead events are dropped from the build."""
from __future__ import annotations

from niceevents.suppress import _matches, drop_suppressed


def test_drops_by_url():
    evs = [
        {"title": "Whatever", "town": "Nice", "start": "2026-07-28",
         "url": "https://www.nice.fr/agenda/fete-de-fin-dannee/"},
        {"title": "Real one", "town": "Nice", "start": "2026-07-29",
         "url": "https://example.com/x"},
    ]
    out = drop_suppressed(evs)
    assert len(out) == 1 and out[0]["title"] == "Real one"


def test_url_line_is_specific():
    # A URL line must not drop a same-titled event at a different URL.
    line = ("https://www.nice.fr/agenda/fete-de-fin-dannee/", None, None, None)
    other = {"title": "Fête de fin d’année", "town": "Nice",
             "start": "2026-12-31", "url": "https://elsewhere.example/party"}
    assert not _matches(other, *line)


def test_title_town_date_line():
    line = (None, "fete de fin d annee", "Nice", "2026-07-28")
    hit = {"title": "Fête de fin d’année", "town": "Nice", "start": "2026-07-28"}
    miss_date = {"title": "Fête de fin d’année", "town": "Nice", "start": "2026-12-31"}
    miss_town = {"title": "Fête de fin d’année", "town": "Menton", "start": "2026-07-28"}
    assert _matches(hit, *line)
    assert not _matches(miss_date, *line)
    assert not _matches(miss_town, *line)


def test_all_none_line_is_noop():
    # A line of all wildcards must not wipe the whole feed.
    keep = {"title": "Anything", "town": "Nice", "start": "2026-07-28"}
    assert _matches(keep, None, None, None, None) is False
