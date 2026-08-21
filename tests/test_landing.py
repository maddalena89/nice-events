"""Town and category landing pages.

Same reasoning as test_seo.py: every failure here is quiet. A landing page that
escapes nothing still renders; a page built for a venue mistaken for a town
still looks like a page; a sitemap that forgot half the site is still valid XML.
None of it throws, so it gets asserted instead.
"""
import html as htmllib
import json
import re
from datetime import date, timedelta
from pathlib import Path

from niceevents import landing, site

BASE = "https://whatsonnice.com"
TPL = Path(__file__).resolve().parent.parent / "templates"


def _ev(**kw):
    d = {"title": "A thing", "start": date.today().isoformat(), "town": "Antibes",
         "venue": "Somewhere", "category": "concert", "slug": "a-thing",
         "note": "", "free": False, "online": False, "time": "20:30"}
    d.update(kw)
    return d


def _many(n, **kw):
    # kw last so a caller can override the generated title/note.
    return [_ev(**{"slug": f"e{i}", "title": f"Event {i}", **kw}) for i in range(n)]


# --- which pages get built -------------------------------------------------

def test_town_needs_enough_events_to_earn_a_page():
    towns, _ = landing.collect(_many(landing.MIN_TOWN_EVENTS, town="Vence"))
    assert [p["name"] for p in towns] == ["Vence"]

    towns, _ = landing.collect(_many(landing.MIN_TOWN_EVENTS - 1, town="Vence"))
    assert towns == []


def test_a_venue_mistaken_for_a_town_gets_no_page():
    """Some sources publish only a venue in their location line, so venue text
    reaches us in `town`. A page headed "What's on in Espace Laure Ecard" is
    both wrong and a thin page search engines dislike."""
    towns, _ = landing.collect(_many(20, town="Espace Laure Ecard"))
    assert towns == []
    # ...but a real commune that merely contains a venue-ish word survives.
    towns, _ = landing.collect(_many(20, town="Villeneuve-Loubet"))
    assert [p["name"] for p in towns] == ["Villeneuve-Loubet"]


def test_online_events_never_make_a_town_page():
    towns, cats = landing.collect(_many(20, town="Online", online=True))
    assert towns == []
    assert cats and cats[0]["events"]      # still counted as a category


def test_events_past_the_window_are_excluded():
    far = (date.today() + timedelta(days=landing.WINDOW_DAYS + 5)).isoformat()
    towns, _ = landing.collect(_many(20, town="Vence", start=far))
    assert towns == []


def test_category_slugs_are_stable_and_reserved():
    """These are public URLs. If a slug ever changes, every indexed link to it
    breaks — so the map is asserted, not derived from the display label."""
    assert landing.CAT_SLUG["concert"] == "concerts"
    assert landing.CAT_SLUG["marche"] == "brocantes-and-fetes"
    for slug in landing.CAT_SLUG.values():
        assert slug in landing.RESERVED_SLUGS


def test_reserved_slugs_do_not_shadow_an_event_short_link():
    """A real directory beats the 404.html short-link redirect, so an event
    whose slug collides with a landing page would lose its short link."""
    events = [{"title": "Concerts", "start": "2026-09-01", "fingerprint": "f1"}]
    site._assign_slugs(events)
    assert events[0]["slug"] != "concerts"


# --- what ends up in the file ---------------------------------------------

def _render(tmp_path, events):
    towns, cats = landing.collect(events)
    written = landing.render_all(TPL, towns, cats, BASE, "21 August 2026",
                                 f"{BASE}/og.png", tmp_path)
    return written, tmp_path


def test_scraped_text_is_escaped_not_injected(tmp_path):
    """Titles come from third-party pages and from a public submission form."""
    evil = '</script><script>window.PWNED=1</script>"><img src=x onerror=alert(1)>'
    _render(tmp_path, _many(6, town="Vence", title=evil, note=evil, venue=evil))
    html = (tmp_path / "in" / "vence" / "index.html").read_text(encoding="utf-8")
    assert "window.PWNED" in html                      # the text is present...
    assert "<script>window.PWNED" not in html          # ...but never as markup
    assert "onerror=alert(1)>" not in html
    assert "&lt;/script&gt;" in html


def test_structured_data_matches_what_the_page_shows(tmp_path):
    _render(tmp_path, _many(8, town="Vence"))
    html = (tmp_path / "in" / "vence" / "index.html").read_text(encoding="utf-8")
    blob = re.search(r'<script type="application/ld\+json">(.*?)</script>', html, re.S).group(1)
    doc = json.loads(blob.replace("\\u003c", "<").replace("\\u003e", ">").replace("\\u0026", "&"))
    assert doc["@type"] == "ItemList"
    assert doc["numberOfItems"] == len(doc["itemListElement"]) == 8
    assert doc["url"] == f"{BASE}/in/vence/"
    assert [i["position"] for i in doc["itemListElement"]] == list(range(1, 9))


def test_jsonld_never_describes_rows_that_were_trimmed_off(tmp_path):
    """Marking up events a visitor cannot see on the page is exactly what a
    structured-data mismatch penalty is for."""
    _render(tmp_path, _many(landing.MAX_JSONLD + 40, town="Vence"))
    html = (tmp_path / "in" / "vence" / "index.html").read_text(encoding="utf-8")
    blob = re.search(r'<script type="application/ld\+json">(.*?)</script>', html, re.S).group(1)
    doc = json.loads(blob.replace("\\u003c", "<").replace("\\u003e", ">").replace("\\u0026", "&"))
    rows = html.count('<div class="row">')
    assert doc["numberOfItems"] == landing.MAX_JSONLD <= rows


def test_page_carries_its_own_canonical_and_title(tmp_path):
    _render(tmp_path, _many(8, town="Vence"))
    html = (tmp_path / "in" / "vence" / "index.html").read_text(encoding="utf-8")
    assert f'<link rel="canonical" href="{BASE}/in/vence/">' in html
    # Decoded, because autoescape writes the apostrophe as &#39; and the
    # ampersand as &amp; — correct HTML, but not what a reader or a crawler sees.
    text = htmllib.unescape(html)
    assert "<title>What's on in Vence · events, concerts & brocantes" in text
    assert "Que faire à Vence" in text          # the French phrasing people search


# --- the sitemap has to name them, or nothing finds them -------------------

def test_sitemap_lists_every_generated_page():
    extra = ["/in/nice/", "/concerts/"]
    xml = site._sitemap(BASE, date(2026, 8, 21), extra)
    for path in ["/", "/privacy.html", *extra]:
        assert f"<loc>{BASE}{path}</loc>" in xml
    assert xml.count("<url>") == 4


def test_sitemap_without_landing_pages_is_still_valid():
    xml = site._sitemap(BASE, date(2026, 8, 21))
    assert xml.count("<url>") == 2
