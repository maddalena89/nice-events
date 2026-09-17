"""Meetup: the paging walk, and the fallback that had quietly stopped working.

Shapes here were copied from real /find/ responses captured 2026-08-27. Two
things are worth stating because both were live bugs:

  * /find/ returns twelve results and then says `hasNextPage: true`. There is no
    reachable page two, so the ONLY way to see the rest is to ask a narrower
    date question. If _walk stops subdividing, the site silently loses most of
    Meetup — which is what it had been doing.
  * the card fallback keyed off a data-testid Meetup deleted. It matched
    nothing, so it yielded nothing, and the "safety net" was a hole that no test
    would have noticed because the primary path was fine.
"""
import json
import re
from datetime import date, timedelta

from niceevents.scrapers.meetup import (
    CATEGORIES, IN_PERSON, MAX_REQUESTS, ONLINE, PAGE_SIZE, Meetup, _has_next_page,
)

TOMORROW = (date.today() + timedelta(days=1)).isoformat()


def _next_data(events, has_next):
    """The SSR payload, shaped like Meetup's: events buried in __APOLLO_STATE__
    at an unpredictable depth, with a PageInfo somewhere alongside."""
    state = {f"Event:{i}": e for i, e in enumerate(events)}
    state["ROOT_QUERY"] = {
        "eventSearch": {
            "pageInfo": {"__typename": "PageInfo",
                         "hasNextPage": has_next, "endCursor": "MTI="}
        }
    }
    doc = {"props": {"pageProps": {"__APOLLO_STATE__": state}}}
    return ('<html><body><script id="__NEXT_DATA__" type="application/json">'
            + json.dumps(doc) + "</script></body></html>")


def _event(i, when=None, **kw):
    e = {"title": f"Event {i}", "dateTime": (when or TOMORROW) + "T19:00:00+02:00",
         "eventUrl": f"https://www.meetup.com/g/events/{i}/",
         "venue": {"name": "Somewhere", "city": "Nice"}}
    e.update(kw)
    return e


# --- the signal the whole walk turns on ------------------------------------

def test_has_next_page_reads_meetups_own_flag():
    assert _has_next_page(json.loads(re.search(
        r'>(\{.*\})<', _next_data([_event(1)], True)).group(1))) is True
    assert _has_next_page(json.loads(re.search(
        r'>(\{.*\})<', _next_data([_event(1)], False)).group(1))) is False


def test_parse_reports_fullness_so_the_walk_can_split():
    m = Meetup()
    evs, more = m._parse(_next_data([_event(i) for i in range(12)], True))
    assert len(evs) == 12 and more is True

    evs, more = m._parse(_next_data([_event(i) for i in range(3)], False))
    assert len(evs) == 3 and more is False


# --- the sweep ----------------------------------------------------------------

class _FakeMeetup:
    """Serves a calendar twelve at a time, honouring the day window and the
    in-person filter — the two behaviours the sweep depends on."""

    def __init__(self, by_day, online_by_day=None):
        self.by_day = by_day                      # {iso_date: n_in_person}
        self.online_by_day = online_by_day or {}
        self.urls = []

    def get(self, url, wait_for=None, scroll=0):
        self.urls.append(url)
        day = re.search(r"customStartDate=(\d{4}-\d{2}-\d{2})", url).group(1)
        online = "eventType=online" in url
        n = (self.online_by_day if online else self.by_day).get(day, 0)
        cat = re.search(r"categoryId=(\d+)", url)
        if cat:
            # A category split serves a fixed slice, so the day converges.
            n = min(n, 2)
        evs = [_event(f"{day}-{'o' if online else 'p'}-{i}", when=day)
               for i in range(min(n, PAGE_SIZE))]
        return _next_data(evs, has_next=n > PAGE_SIZE and not cat)


def _iso(offset):
    return (date.today() + timedelta(days=offset)).isoformat()


def test_sweep_asks_for_every_day_in_the_horizon():
    fake = _FakeMeetup({_iso(i): 2 for i in range(5)})
    m = Meetup(); m._requests = 0
    found = {}
    m._sweep(fake.get, IN_PERSON, date.today(), 4, found)
    assert len(fake.urls) == 5, "one request per day"
    assert len(found) == 10


def test_sweep_finds_events_a_wide_window_would_have_hidden():
    """The regression this rewrite exists for: an event far out is invisible to
    a ranked wide-window query, but a day-by-day sweep asks for its day."""
    cal = {_iso(i): 4 for i in range(20)}
    cal[_iso(85)] = 1
    fake = _FakeMeetup(cal)
    m = Meetup(); m._requests = 0
    found = {}
    m._sweep(fake.get, IN_PERSON, date.today(), 90, found)
    assert any(e.start.isoformat() == _iso(85) for e in found.values())
    assert len(found) == 20 * 4 + 1


def test_sweep_splits_a_day_that_overflows():
    """A day that fills the page is re-asked per category, since that is the
    only other axis the server honours."""
    fake = _FakeMeetup({_iso(0): 40})
    m = Meetup(); m._requests = 0
    found = {}
    m._sweep(fake.get, IN_PERSON, date.today(), 0, found)
    assert any("categoryId=" in u for u in fake.urls), "did not split a full day"
    assert len(fake.urls) == 1 + len(CATEGORIES)


def test_sweep_does_not_split_a_day_with_room_to_spare():
    fake = _FakeMeetup({_iso(0): 5})
    m = Meetup(); m._requests = 0
    found = {}
    m._sweep(fake.get, IN_PERSON, date.today(), 0, found)
    assert fake.urls == [Meetup._url(IN_PERSON, date.today(), date.today())]


def test_sweep_respects_the_request_ceiling():
    fake = _FakeMeetup({_iso(i): 3 for i in range(200)})
    m = Meetup(); m._requests = MAX_REQUESTS
    found = {}
    m._sweep(fake.get, IN_PERSON, date.today(), 90, found)
    assert fake.urls == []


def test_online_days_are_not_split_by_category():
    """Nearly every online day is full. Splitting them would cost twenty extra
    requests each — more than the entire in-person sweep — to enumerate
    webinars the site hides by default."""
    fake = _FakeMeetup({}, online_by_day={_iso(0): 40})
    m = Meetup(); m._requests = 0
    found = {}
    m._sweep(fake.get, ONLINE, date.today(), 0, found, split_full_days=False)
    assert len(fake.urls) == 1
    assert not any("categoryId=" in u for u in fake.urls)


def test_in_person_and_online_are_separate_sweeps():
    """Online is asked for separately, so its horizon can be shorter and its
    events still arrive flagged."""
    fake = _FakeMeetup({_iso(0): 2}, online_by_day={_iso(0): 2})
    m = Meetup(); m._requests = 0
    found = {}
    m._sweep(fake.get, IN_PERSON, date.today(), 0, found)
    m._sweep(fake.get, ONLINE, date.today(), 0, found)
    assert len(found) == 4
    assert sum("eventType=inPerson" in u for u in fake.urls) == 1
    assert sum("eventType=online" in u for u in fake.urls) == 1


def test_a_missing_page_does_not_abort_the_sweep():
    calls = {"n": 0}

    def flaky(url, wait_for=None, scroll=0):
        calls["n"] += 1
        return None if calls["n"] == 2 else _next_data([_event(calls["n"])], False)

    m = Meetup(); m._requests = 0
    found = {}
    m._sweep(flaky, IN_PERSON, date.today(), 3, found)
    assert calls["n"] == 4, "one bad day must not stop the rest"
    assert len(found) == 3


# --- URLs and categories ----------------------------------------------------

def test_url_carries_the_window_and_the_venue_filter():
    u = Meetup._url(IN_PERSON, date(2026, 9, 1), date(2026, 9, 1))
    assert "customStartDate=2026-09-01" in u and "customEndDate=2026-09-01" in u
    assert "location=fr--nice" in u
    # Spelling is load-bearing: Meetup silently ignores "IN_PERSON", which looks
    # like a working filter and quietly returns the unfiltered firehose.
    assert "eventType=inPerson" in u
    assert "categoryId" not in u, "the day sweep must not pin a category"
    assert "categoryId=511" in Meetup._url(IN_PERSON, date(2026, 9, 1),
                                           date(2026, 9, 1), "511")


def test_health_and_wellbeing_is_covered():
    """The category whose absence started this — keyword search never had it."""
    assert CATEGORIES["511"] == "Health & Wellbeing"
    assert len(CATEGORIES) == 20


# --- the fallback -----------------------------------------------------------

def _card(i, when):
    """A rendered card, shaped like Meetup's: the whole tile is one <a>, with a
    machine-readable <time> inside. Deliberately NO data-testid — that is the
    attribute that disappeared."""
    return (f'<div><a href="https://www.meetup.com/grp/events/{200+i}/">'
            f'<h3>Real Title {i}</h3>'
            f'<time datetime="{when}T18:30:00+02:00[Europe/Paris]">'
            f'Aug · 6:30 PM</time></a></div>')


def test_card_fallback_still_reads_todays_markup():
    m = Meetup()
    html = "<html><body>" + "".join(_card(i, TOMORROW) for i in range(4)) + "</body></html>"
    evs, _ = m._parse(html)
    assert len(evs) == 4, "fallback found nothing in current markup"
    assert {e.title for e in evs} == {f"Real Title {i}" for i in range(4)}


def test_card_fallback_gives_each_card_its_own_title():
    """The bug: climbing to a shared ancestor made every card report the first
    card's title."""
    m = Meetup()
    html = ("<html><body><div class='grid'>"
            + "".join(_card(i, TOMORROW) for i in range(5))
            + "</div></body></html>")
    evs, _ = m._parse(html)
    assert len({e.title for e in evs}) == 5
    assert len({e.url for e in evs}) == 5


def test_next_data_wins_over_cards_when_both_are_present():
    m = Meetup()
    nd = _next_data([_event(1)], False)
    html = nd.replace("</body>", _card(9, TOMORROW) + "</body>")
    evs, _ = m._parse(html)
    assert [e.title for e in evs] == ["Event 1"]


def test_online_sweep_trusts_its_own_filter():
    """Asking Meetup for online events is better evidence than reading the
    title: a webinar called "Marketing Workshop" says nothing about format."""
    m = Meetup()
    plain = _event(1, title="Marketing Workshop")     # nothing says "online"
    evs, _ = m._parse(_next_data([plain], False), online=True)
    assert evs[0].online is True
    assert evs[0].town == "Online"

    evs, _ = m._parse(_next_data([plain], False), online=False)
    assert evs[0].online is False, "an in-person result must not be flagged"


def test_card_fallback_also_honours_the_online_hint():
    m = Meetup()
    html = "<html><body>" + _card(1, TOMORROW) + "</body></html>"
    evs, _ = m._parse(html, online=True)
    assert evs[0].online is True and evs[0].town == "Online"
