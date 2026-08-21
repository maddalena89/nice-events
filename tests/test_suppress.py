"""Phantom / dead events are dropped from the build."""
from __future__ import annotations

import niceevents.suppress as suppress
from niceevents.suppress import _matches, drop_suppressed


def test_drops_by_url(monkeypatch):
    # Test the mechanism with a temporary rule, not whatever is in the live list
    # (which should normally be empty).
    monkeypatch.setattr(
        suppress, "SUPPRESSED",
        [("https://example.com/dead/", None, None, None)],
    )
    evs = [
        {"title": "Whatever", "town": "Nice", "start": "2026-07-28",
         "url": "https://example.com/dead/"},
        {"title": "Real one", "town": "Nice", "start": "2026-07-29",
         "url": "https://example.com/x"},
    ]
    out = drop_suppressed(evs)
    assert len(out) == 1 and out[0]["title"] == "Real one"


def test_empty_suppressed_list_is_noop(monkeypatch):
    monkeypatch.setattr(suppress, "SUPPRESSED", [])
    evs = [{"title": "Anything", "town": "Nice", "start": "2026-07-28"}]
    assert drop_suppressed(evs) == evs


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


# --------------------------------------------------------- Jazz au Château
#
# Reported 2026-08-21: the row never said which band was playing. The tourist
# office publishes the festival as one umbrella entry (26 Jun - 11 Sep) that
# names no act, and browsing Concerts repeated it on every day of its run, on
# top of the per-night rows that DO name the band. Same shape as the Trinquette
# umbrella, and suppressed the same way.

def test_the_jazz_au_chateau_umbrella_is_dropped_but_the_bands_are_not():
    """Uses the LIVE list on purpose: this asserts the real rule is present and
    correctly scoped, not that the mechanism works (test_drops_by_url does that)."""
    umbrella = "https://www.explorenicecotedazur.com/en/event/jazz-at-the-chateau/"
    nights = "https://ville.cagnes.fr/actualites-csm/jazz-au-chateau-2026/"
    evs = [
        {"title": "Jazz at the Château", "town": "Cagnes-sur-Mer",
         "start": "2026-06-26", "end": "2026-09-11", "url": umbrella},
        # the same page again, a year out because its card carries no year
        {"title": "Jazz at the Château", "town": "Cagnes-sur-Mer",
         "start": "2027-06-26", "url": umbrella},
        {"title": "The Jazz Bicravers", "town": "Cagnes-sur-Mer",
         "start": "2026-08-21", "url": nights},
        {"title": "Les Accordes Swing", "town": "Cagnes-sur-Mer",
         "start": "2026-08-28", "url": nights},
    ]
    kept = [e["title"] for e in drop_suppressed(evs)]
    assert kept == ["The Jazz Bicravers", "Les Accordes Swing"]
