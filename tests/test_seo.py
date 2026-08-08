"""Structured data and sitemap.

These exist because the failure mode here is silent. Malformed JSON-LD does not
break the page, throw, or show up in any test that looks at the HTML: the site
renders perfectly and Google simply declines to use the markup, which nobody
notices for months. So the invariants Search Console actually enforces are
asserted here instead.
"""
import json
from datetime import date

from niceevents import site

BASE = "https://whatsonnice.com"
TODAY = date(2026, 8, 6)


def _ld(events, today=TODAY):
    blob = site._events_jsonld(events, BASE, today=today)
    return json.loads(blob) if blob else []


def _ev(**kw):
    base = {"title": "A thing", "start": "2026-08-07", "town": "Nice",
            "venue": "Somewhere", "category": "concert", "slug": "a-thing"}
    base.update(kw)
    return base


# --- the offset, which is the whole reason times are trustworthy -----------

def test_paris_offset_summer_and_winter():
    assert site._paris_offset(date(2026, 8, 7)) == "+02:00"
    assert site._paris_offset(date(2026, 1, 7)) == "+01:00"


def test_paris_offset_switches_on_the_last_sunday():
    # 2026: clocks go forward Sun 29 Mar, back Sun 25 Oct.
    assert site._paris_offset(date(2026, 3, 28)) == "+01:00"
    assert site._paris_offset(date(2026, 3, 29)) == "+02:00"
    assert site._paris_offset(date(2026, 10, 24)) == "+02:00"
    assert site._paris_offset(date(2026, 10, 25)) == "+01:00"


def test_no_time_means_no_invented_time():
    """A date with no start time must stay a date. Padding it to T00:00 would
    claim a midnight start the source never gave."""
    assert site._ld_datetime("2026-08-07", None) == "2026-08-07"
    assert site._ld_datetime("2026-08-07", "20:30") == "2026-08-07T20:30:00+02:00"


# --- required fields -------------------------------------------------------

def test_every_event_has_the_three_required_fields():
    out = _ld([_ev(), _ev(start="2026-08-20", slug="b"), _ev(start="2026-09-01", slug="c")])
    assert len(out) == 3
    for e in out:
        assert e["name"] and e["startDate"] and e["location"]
        assert e["@context"] == "https://schema.org"
        assert e["@type"] == "Event"


def test_place_always_has_a_name_even_with_no_venue():
    """Google rejects a Place with no name, so the town stands in for a missing
    venue rather than emitting an empty string."""
    out = _ld([_ev(venue=None)])
    assert out[0]["location"]["name"] == "Nice"


# --- the bug this file was written for ------------------------------------

def test_same_day_end_is_omitted_not_emitted_as_midnight():
    """end == start with a timed start used to produce
    startDate 2026-08-07T17:30+02:00 / endDate 2026-08-07, i.e. an event ending
    before it began. Invalid, and Search Console drops the item for it."""
    out = _ld([_ev(start="2026-08-07", end="2026-08-07", time="17:30")])
    assert "endDate" not in out[0]


def test_a_real_multi_day_run_keeps_its_end_date():
    out = _ld([_ev(start="2026-08-07", end="2026-08-09")])
    assert out[0]["endDate"] == "2026-08-09"
    assert out[0]["endDate"] > out[0]["startDate"][:10]


# --- states ----------------------------------------------------------------

def test_cancelled_events_say_so():
    out = _ld([_ev(cancelled=True)])
    assert out[0]["eventStatus"] == "https://schema.org/EventCancelled"


def test_online_events_use_a_virtual_location():
    out = _ld([_ev(online=True, url="https://example.com/x")])
    assert out[0]["location"]["@type"] == "VirtualLocation"
    assert out[0]["eventAttendanceMode"].endswith("OnlineEventAttendanceMode")


def test_free_flag_survives_but_no_price_is_invented():
    out = _ld([_ev(free=True)])
    assert out[0]["isAccessibleForFree"] is True
    assert "offers" not in out[0]          # we don't know the price; don't guess


# --- windowing -------------------------------------------------------------

def test_far_future_and_past_events_are_left_out():
    out = _ld([
        _ev(start="2026-07-01", slug="past"),
        _ev(start="2026-08-07", slug="soon"),
        _ev(start="2027-06-01", slug="far"),
    ])
    assert [e["url"].rsplit("=", 1)[1] for e in out] == ["soon"]


def test_the_list_is_capped():
    many = [_ev(start="2026-08-07", slug=f"e{i}") for i in range(site._LD_MAX + 40)]
    assert len(_ld(many)) == site._LD_MAX


# --- injection -------------------------------------------------------------

def test_a_title_cannot_close_the_script_tag():
    """The blob is dropped inside <script>. A scraped title containing a literal
    </script> would end the element early and spill JSON onto the page."""
    blob = site._events_jsonld([_ev(title="Bal </script><img src=x> & co")], BASE, today=TODAY)
    assert "</script>" not in blob
    assert "<" not in blob and ">" not in blob and "&" not in blob
    # …and it still round-trips to the original text.
    assert json.loads(blob)[0]["name"] == "Bal </script><img src=x> & co"


def test_no_host_means_no_markup_rather_than_broken_urls():
    assert site._events_jsonld([_ev()], "", today=TODAY) == ""


# --- sitemap ---------------------------------------------------------------

def test_sitemap_lists_real_pages_only():
    xml = site._sitemap(BASE, TODAY)
    assert "<loc>https://whatsonnice.com/</loc>" in xml
    assert "<loc>https://whatsonnice.com/privacy.html</loc>" in xml
    assert "<lastmod>2026-08-06</lastmod>" in xml
    # The pretty short links are served by 404.html and bounced with JS. Listing
    # them would fill the sitemap with soft 404s.
    assert "?e=" not in xml
