"""A town page, once published, must not start 404ing.

Menton had a page, dropped to four events, and the URL died — while llms.txt
went on telling AI crawlers to read it and Google went on reporting it as a
404. These tests pin the rule that replaced that: built once, kept for good.
"""
from datetime import date, timedelta
from pathlib import Path

from niceevents import landing

#: Inside the 90-day window collect() looks at — a date beyond it is filtered
#: out before any of this runs, which makes for a very confusing test failure.
SOON = (date.today() + timedelta(days=7)).isoformat()


def _ev(town, n, start=SOON):
    return [{"title": f"{town} thing {i}", "start": start, "end": None,
             "time": "20:00", "town": town, "venue": "Somewhere",
             "category": "concert", "tags": ["concert"], "url": "https://x.test/"}
            for i in range(n)]


def test_town_below_threshold_keeps_its_page_once_published():
    events = _ev("Nice", 9) + _ev("Menton", 2)
    towns, _ = landing.collect(events)
    assert not any(p["name"] == "Menton" for p in towns), "two events should not earn a page"

    towns, _ = landing.collect(events, {"menton": "Menton"})
    menton = [p for p in towns if p["name"] == "Menton"]
    assert menton, "a page that existed before must still be built"
    assert menton[0]["thin"] is True
    assert menton[0]["path"] == "/in/menton/"
    assert len(menton[0]["events"]) == 2, "it still shows what little is on"


def test_kept_page_works_with_no_events_at_all():
    towns, _ = landing.collect(_ev("Nice", 9), {"eze": "Èze"})
    eze = [p for p in towns if p["path"] == "/in/eze/"]
    assert eze and eze[0]["events"] == []
    copy = landing._copy_for(eze[0], len(towns))
    assert "Nothing" in copy["lede"] or "nothing" in copy["lede"]
    assert "Èze" in copy["title"]


def test_a_town_that_qualifies_today_is_not_marked_thin():
    towns, _ = landing.collect(_ev("Nice", 9) + _ev("Menton", 7), {"menton": "Menton"})
    menton = [p for p in towns if p["name"] == "Menton"][0]
    assert menton["thin"] is False
    assert len(menton["events"]) == 7


def test_kept_pages_are_not_offered_in_the_nav():
    towns, cats = landing.collect(_ev("Nice", 9) + _ev("Menton", 1), {"menton": "Menton"})
    town_links, _ = landing.nav_links(towns, cats)
    assert [t["name"] for t in town_links] == ["Nice"]


def test_kept_pages_are_written_but_left_out_of_the_sitemap(tmp_path):
    towns, cats = landing.collect(_ev("Nice", 9) + _ev("Menton", 1), {"menton": "Menton"})
    tpl = Path(__file__).resolve().parent.parent / "templates"
    written = landing.render_all(tpl, towns, cats, "https://x.test", "today",
                                 og_image="", out=tmp_path)
    assert (tmp_path / "in" / "menton" / "index.html").exists(), "the URL must resolve"
    assert "/in/menton/" not in written, "but it is not advertised while thin"
    assert "/in/nice/" in written


def test_the_record_survives_a_round_trip(tmp_path):
    import sqlite3
    from niceevents import db
    conn = sqlite3.connect(tmp_path / "t.db")
    conn.row_factory = sqlite3.Row
    conn.executescript(db.SCHEMA)
    assert db.known_town_pages(conn) == {}
    db.remember_town_pages(conn, [("menton", "Menton"), ("nice", "Nice")])
    assert db.known_town_pages(conn) == {"menton": "Menton", "nice": "Nice"}
    db.remember_town_pages(conn, [("menton", "Menton")])   # re-run, same day
    assert len(db.known_town_pages(conn)) == 2, "recording twice must not duplicate"
