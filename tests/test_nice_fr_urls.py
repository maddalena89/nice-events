"""nice.fr link picking: never publish a permalink the city does not serve.

The 2026-08-08 health check found six in-window events whose `url` 404d. The
scraper was not at fault in the obvious way — it never slugified anything, it
took `item["link"]` straight from the WordPress API. nice.fr itself returns
`status: publish` with an `/agenda/<slug>/` permalink that its own front end
answers with a 404.

Two signals in the same API response tell a served permalink from a dead one:

* `acf.external_link` set — /agenda/<slug>/ exists only as a redirect to the
  museum or library that owns the page. Working, and we prefer the destination.
* the slug appears in event-sitemap1.xml — a real page.

Neither → dead, so fall back to `acf.pages`, the programme page the event
belongs to, and failing that publish no link at all.

Checked against the live API on 2026-08-08: the rule agreed with the real HTTP
status on 60 of 60 randomly sampled events.
"""
from __future__ import annotations

from datetime import date

from niceevents.scrapers.nice_fr import NiceFr, _LOC

SITEMAP_XML = """<?xml version="1.0"?>
<urlset>
  <url><loc>https://www.nice.fr/agenda/rorqual/</loc></url>
  <url><loc>https://www.nice.fr/agenda/fete-de-lassomption/</loc></url>
</urlset>"""


def _scraper(live=None, pages=None):
    s = NiceFr.__new__(NiceFr)
    s._places, s._types, s._pages = {}, {}, dict(pages or {})
    s._live = live
    return s


def _item(slug, *, external="", pages=None):
    return {
        "slug": slug,
        "link": f"https://www.nice.fr/agenda/{slug}/",
        "acf": {"external_link": {"label": "", "url": external}, "pages": pages or []},
    }


def test_sitemap_regex_reads_slugs():
    assert set(_LOC.findall(SITEMAP_XML)) == {"rorqual", "fete-de-lassomption"}


def test_ticketing_wins_over_everything():
    s = _scraper(live={"rorqual"})
    it = _item("rorqual", external="https://elsewhere.example/x")
    url = s._url_for(it, it["acf"], {"ticketing": "https://tickets.example/abc"})
    assert url == "https://tickets.example/abc"


def test_external_link_preferred_over_the_redirect_stub():
    """Working today, but via a redirect. Publish the destination, not the hop."""
    s = _scraper(live=set())
    it = _item("visite-guidee-en-famille",
               external="https://www.musee-matisse-nice.org/fr/evenement/visite/")
    assert s._url_for(it, it["acf"], {}) == \
        "https://www.musee-matisse-nice.org/fr/evenement/visite/"


def test_permalink_kept_when_the_sitemap_lists_it():
    s = _scraper(live={"rorqual"})
    it = _item("rorqual")
    assert s._url_for(it, it["acf"], {}) == "https://www.nice.fr/agenda/rorqual/"


def test_dead_permalink_falls_back_to_the_programme_page():
    """The real 2026-08-08 case: Madagascar, live event, 404 link."""
    s = _scraper(live={"rorqual"}, pages={8997: "https://www.nice.fr/mon-ete-cinema/"})
    it = _item("madagascar", pages=[8997, 6945])
    assert s._url_for(it, it["acf"], {}) == "https://www.nice.fr/mon-ete-cinema/"


def test_first_resolving_page_wins_when_an_earlier_one_is_dead():
    s = _scraper(live=set(), pages={1: None, 2: "https://www.nice.fr/mon-ete-a-nice/"})
    it = _item("madagascar", pages=[1, 2])
    assert s._url_for(it, it["acf"], {}) == "https://www.nice.fr/mon-ete-a-nice/"


def test_no_link_at_all_rather_than_a_404():
    s = _scraper(live=set())
    it = _item("la-farandole-animation-musicale")
    assert s._url_for(it, it["acf"], {}) is None


def test_unreadable_sitemap_fails_open_and_keeps_the_api_link():
    """A sitemap fetch failure must not strip the url off every nice.fr event."""
    s = _scraper(live=None)
    it = _item("anything-at-all")
    assert s._url_for(it, it["acf"], {}) == "https://www.nice.fr/agenda/anything-at-all/"


def test_events_from_uses_the_picked_url():
    s = _scraper(live=set(), pages={17349: "https://www.nice.fr/la-farandole/"})
    item = _item("la-farandole-spectacle-douverture", pages=[17349])
    item["title"] = {"rendered": "La Farandole, spectacle d’ouverture"}
    item["excerpt"] = {"rendered": "Animation"}
    item["acf"]["event_dates"] = [{"start_date": "20260813", "start_time": "18:00:00"}]
    evs = list(s._events_from(item, date(2026, 8, 1)))
    assert len(evs) == 1
    assert evs[0].url == "https://www.nice.fr/la-farandole/"
