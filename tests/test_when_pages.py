"""Pages for WHEN: ce soir, ce week-end, aujourd'hui, cette semaine, gratuit.

These exist because the searches people actually type are about time ("que
faire à Nice ce week-end"), and until 9 Nov 2026 the site had no page about any
of them.
"""
from datetime import date, timedelta

from niceevents.landing import _weekend, collect_when, when_links


def ev(start, time=None, free=False, end=None, **kw):
    d = {"title": "x", "town": "Nice", "start": start, "time": time, "free": free,
         "category": "concert"}
    if end:
        d["end"] = end
    d.update(kw)
    return d


MON = date(2026, 11, 9)          # a Monday


def test_the_weekend_means_the_coming_saturday_and_sunday():
    assert _weekend(MON) == ("2026-11-14", "2026-11-15")
    # ...and on the Sunday itself, the weekend you are standing in.
    assert _weekend(date(2026, 11, 15)) == ("2026-11-14", "2026-11-15")


def _pages(events, today=MON):
    return {p["key"]: p for p in collect_when(events, today=today)}


def test_tonight_is_this_evening_only():
    evs = [ev("2026-11-09", "20:00"), ev("2026-11-09", "21:00"), ev("2026-11-09", "18:30"),
           ev("2026-11-09", "10:00"), ev("2026-11-10", "20:00")]
    p = _pages(evs)["tonight"]
    assert len(p["events"]) == 3 and p["path"] == "/ce-soir/"


def test_the_weekend_page_holds_saturday_and_sunday():
    evs = [ev("2026-11-14"), ev("2026-11-14"), ev("2026-11-15"), ev("2026-11-11")]
    assert len(_pages(evs)["weekend"]["events"]) == 3


def test_a_run_spanning_the_weekend_counts():
    evs = [ev("2026-11-01", end="2026-11-30")] * 3
    assert len(_pages(evs)["weekend"]["events"]) == 3


def test_free_means_free_and_soon():
    evs = [ev("2026-11-10", free=True), ev("2026-11-11", free=True), ev("2026-11-12", free=True),
           ev("2026-11-10"), ev("2026-12-25", free=True)]
    assert len(_pages(evs)["free"]["events"]) == 3


def test_online_and_cancelled_events_are_not_somewhere_to_go():
    evs = [ev("2026-11-09", "20:00", online=True), ev("2026-11-09", "20:00", cancelled=True),
           ev("2026-11-09", "20:00"), ev("2026-11-09", "21:00"), ev("2026-11-09", "22:00")]
    assert len(_pages(evs)["tonight"]["events"]) == 3


def test_a_page_with_almost_nothing_on_it_is_not_built():
    assert "tonight" not in _pages([ev("2026-11-09", "20:00"), ev("2026-11-09", "21:00")])


def test_the_nav_reads_in_the_order_of_a_day():
    evs = [ev("2026-11-09", "20:00")] * 3 + [ev("2026-11-14")] * 3 + [ev("2026-11-10", free=True)] * 3
    names = [l["name"] for l in when_links(collect_when(evs, today=MON))]
    assert names[0] == "Tonight" and names[-1] == "Free"
