"""explore_nca reads venue, start time and description off the event page.

21 August 2026: every one of this source's ~420 events reached the site with no
venue, no start time and a description like "Theme evenings DJ", because the
scraper only ever read the listing card. The detail page has all three in
JSON-LD. These pin the parsing against the real page shapes, offline.
"""
from __future__ import annotations

from datetime import date

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
