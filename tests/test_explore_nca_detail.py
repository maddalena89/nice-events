"""explore_nca reads venue, start time and description off the event page.

21 August 2026: every one of this source's ~420 events reached the site with no
venue, no start time and a description like "Theme evenings DJ", because the
scraper only ever read the listing card. The detail page has all three in
JSON-LD. These pin the parsing against the real page shapes, offline.
"""
from __future__ import annotations

from datetime import date

from niceevents.models import Event
from niceevents.scrapers.explore_nca import ExploreNCA


class _Resp:
    def __init__(self, text): self.text = text


def _detail(html, start=date(2026, 8, 21)):
    s = ExploreNCA.__new__(ExploreNCA)
    s.get = lambda url, **kw: _Resp(html)
    return s._detail("https://example.invalid/e/", start)


FULL = """
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"Articles","name":"Pool Party",
 "description":"A festive atmosphere\\n in the pool!",
 "address":{"@type":"PostalAddress","addressLocality":"Saint-Martin-Vesubie",
            "postalCode":"06450","streetAddress":"Allees du Docteur Fulconis"},
 "openingHoursSpecification":[
   {"dayOfWeek":"Thursday","validFrom":"2026-08-20","validThrough":"2026-08-20","opens":"10:00","closes":"12:00"},
   {"dayOfWeek":"Friday","validFrom":"2026-08-21","validThrough":"2026-08-21","opens":"19:00","closes":"21:00"}]}
</script>
<p itemprop="address">Vesubia Mountain Park Allees du Docteur Fulconis 06450 Saint-Martin-Vesubie</p>
"""

# Real shape from club-sonore: no streetAddress, so nothing gets subtracted and
# the whole address used to survive as the venue.
NO_STREET = """
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"Articles","name":"Club Sonore",
 "description":"Every Wednesday, the beach comes alive with the parties."}
</script>
<p itemprop="address">Plage Bocca Mar 15 Promenade des Anglais 06000 Nice</p>
"""


def test_venue_time_and_description_are_read():
    got = _detail(FULL)
    assert got["venue"] == "Vesubia Mountain Park"
    assert got["time"] == "19:00"
    assert got["note"] == "A festive atmosphere in the pool!"      # newline collapsed


def test_the_hours_for_the_listed_date_are_chosen():
    """A summer-long run has one spec per night; take the one being listed."""
    assert _detail(FULL, date(2026, 8, 20))["time"] == "10:00"
    assert _detail(FULL, date(2026, 8, 21))["time"] == "19:00"


def test_an_address_with_no_street_field_is_still_trimmed_to_the_venue():
    assert _detail(NO_STREET)["venue"] == "Plage Bocca Mar"


def test_a_numbered_venue_is_not_truncated():
    """No postcode means no address is attached, so "Le 109" survives intact."""
    html = '<script type="application/ld+json">{"name":"X","description":"aaaaaaaaaaaaaaaaaa"}</script>' \
           '<p itemprop="address">Le 109</p>'
    assert _detail(html)["venue"] == "Le 109"


def test_a_page_that_fails_to_load_loses_nothing():
    s = ExploreNCA.__new__(ExploreNCA)
    s.get = lambda url, **kw: None
    assert s._detail("https://example.invalid/e/", date(2026, 8, 21)) == {}


def test_junk_json_ld_does_not_raise():
    assert _detail('<script type="application/ld+json">{ not json </script>') == {}


# ------------------------------------------------------------ the crawl budget
#
# Enriching all ~420 events blew the job's 45 minute timeout on 2026-08-21 and
# GitHub cancelled the run. The detail crawl is bounded two ways now.

from datetime import timedelta


def _harness(starts, monkeypatch):
    """Run fetch() over a fake listing and record which events got enriched."""
    from niceevents.scrapers import explore_nca as mod
    s = ExploreNCA.__new__(ExploreNCA)
    evs = [Event(title=f"E{i}", start=d, town="Nice",
                 url=f"https://x.invalid/{i}", source="explore_nca")
           for i, d in enumerate(starts)]
    s.get = lambda url, **kw: _Resp("")
    monkeypatch.setattr(mod, "FEEDS", [("/p/", 1)])
    monkeypatch.setattr(ExploreNCA, "_parse", lambda self, html: iter(evs))
    hit = []
    monkeypatch.setattr(ExploreNCA, "_detail",
                        lambda self, url, start: hit.append(url) or {})
    out = list(s.fetch())
    return out, hit


def test_far_future_events_are_published_but_not_enriched(monkeypatch):
    from niceevents.models import Event as _E
    today = date.today()
    starts = [today + timedelta(days=5), today + timedelta(days=400)]
    out, hit = _harness(starts, monkeypatch)
    assert len(out) == 2, "everything is still published"
    assert len(hit) == 1, "only the near one costs a request"


def test_the_hard_cap_holds_even_inside_the_horizon(monkeypatch):
    today = date.today()
    starts = [today + timedelta(days=i % 100) for i in range(400)]
    out, hit = _harness(starts, monkeypatch)
    assert len(out) == 400
    assert len(hit) == ExploreNCA.MAX_DETAIL


def test_the_budget_goes_to_the_soonest_events(monkeypatch):
    today = date.today()
    starts = [today + timedelta(days=d) for d in (90, 1, 45)]
    out, hit = _harness(starts, monkeypatch)
    assert hit == ["https://x.invalid/1", "https://x.invalid/2", "https://x.invalid/0"]


def test_single_day_events_get_the_budget_before_long_runs(monkeypatch):
    """A run that opened in March has opening hours, not a start time, and used
    to sort ahead of a concert next week purely because it started earlier."""
    from niceevents.scrapers import explore_nca as mod
    today = date.today()
    s = ExploreNCA.__new__(ExploreNCA)
    run = Event(title="Expo", start=today - timedelta(days=150),
                end=today + timedelta(days=30), town="Nice",
                url="https://x.invalid/run", source="explore_nca")
    gig = Event(title="Gig", start=today + timedelta(days=7), town="Nice",
                url="https://x.invalid/gig", source="explore_nca")
    s.get = lambda url, **kw: _Resp("")
    monkeypatch.setattr(mod, "FEEDS", [("/p/", 1)])
    monkeypatch.setattr(ExploreNCA, "_parse", lambda self, html: iter([run, gig]))
    monkeypatch.setattr(ExploreNCA, "MAX_DETAIL", 1)
    hit = []
    monkeypatch.setattr(ExploreNCA, "_detail",
                        lambda self, url, start: hit.append(url) or {})
    out = list(s.fetch())
    assert len(out) == 2
    assert hit == ["https://x.invalid/gig"]


# ------------------------------------------------- the time is not in JSON-LD
#
# Only 8 of 177 enriched events had openingHoursSpecification on the first live
# run. The time was on nearly all of them, in the visible date line, and their
# template mangles "18h30" into "18 a.m30" — the "a.m" is a broken "h", not a
# meridiem, so the hour is already 24-hour.

VISIBLE_ONLY = """
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"Articles","name":"Match",
 "description":"Ligue 1 fixture at the Allianz Riviera stadium."}
</script>
<p class="wpet-date reset-margin">The Saturday 22 August at 20 a.m45</p>
<p itemprop="address">Stade Allianz Riviera</p>
"""


def test_the_visible_time_is_used_when_json_ld_has_no_hours():
    assert _detail(VISIBLE_ONLY, date(2026, 8, 22))["time"] == "20:45"


def test_a_mangled_am_is_not_treated_as_a_meridiem():
    """"20 a.m45" is 20:45, never 08:45."""
    got = _detail(VISIBLE_ONLY, date(2026, 8, 22))["time"]
    assert got == "20:45" and not got.startswith("08")


def test_json_ld_hours_still_win_over_the_visible_line():
    both = FULL + '<p class="wpet-date">The Friday 21 August at 23 a.m59</p>'
    assert _detail(both, date(2026, 8, 21))["time"] == "19:00"


def test_a_page_with_neither_yields_no_time():
    assert "time" not in _detail(NO_STREET)
