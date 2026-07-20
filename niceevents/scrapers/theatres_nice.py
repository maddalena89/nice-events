"""Théâtres de Nice — the city's portal for its municipal & partner theatres.

theatres.nice.fr/les-evenements lists, on one page, the whole programme of the
small Nice stages that no API reaches: Théâtre de l'Alphabet, Théâtre de la Cité,
Théâtre Francis-Gag, Théâtre Lino Ventura, the Bouff'Scène café-théâtre and the
TNN. This is the single biggest fix for the empty "Stage & Theatre" category.

The page is server-rendered (Symfony) but plain HTTP came back empty for it —
some UA/edge quirk — so we render it in a browser and read the same DOM. Each
card carries venue (.lieu), genre (.genre), the full title (image alt; the <h2>
is truncated with an ellipsis) and a date, either "Le DD/MM/YYYY" for a one-off
or "Du DD/MM/YYYY au DD/MM/YYYY" for a run.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Iterator, Optional

from selectolax.parser import HTMLParser

from ..models import Event, parse_date
from .base import BrowserScraper, register

BASE = "https://theatres.nice.fr"
URL = f"{BASE}/les-evenements"

_D = re.compile(r"(\d{2}/\d{2}/\d{4})")


def _genre_category(genre: str) -> str:
    """Map the portal's genre label to our category. It's a theatres portal, so
    the default is the stage; only music and dance break away."""
    g = genre.lower()
    if "concert" in g or "jazz" in g or "musique" in g:
        return "concert"
    if "danse" in g or "hip-hop" in g:
        return "danse"
    return "scene"


def _clean(node) -> str:
    return re.sub(r"\s+", " ", (node.text() if node else "") or "").strip()


def _parse(html: str) -> Iterator[Event]:
    tree = HTMLParser(html)
    seen: set[str] = set()
    for a in tree.css('a[href^="/evenement/"]'):
        info = a.css_first(".info-container")
        if not info:
            continue                              # image-only duplicate link
        href = a.attributes.get("href") or ""
        if href in seen:
            continue
        seen.add(href)

        dates = _D.findall(_clean(a.css_first(".date")))
        if not dates:
            continue
        start = parse_date(dates[0])              # DD/MM/YYYY, day-first
        end = parse_date(dates[1]) if len(dates) > 1 else None
        if not start:
            continue

        img = a.css_first("img")
        title = (img.attributes.get("alt") if img else "") or _clean(a.css_first("h2"))
        title = re.sub(r"\s+", " ", title or "").strip().rstrip("…").strip()
        if not title:
            continue

        venue = _clean(a.css_first(".lieu")) or None
        genre = _clean(a.css_first(".genre"))

        yield Event(
            title=title,
            start=start,
            end=end,
            town="Nice",
            venue=venue,
            category=_genre_category(genre),
            url=f"{BASE}{href}",
            note=genre or None,
            source="theatres_nice",
        )


@register
class TheatresNice(BrowserScraper):
    name = "theatres_nice"
    label = "Théâtres de Nice (Alphabet, Cité, Francis-Gag…)"

    def fetch(self) -> Iterator[Event]:
        html = self._page_text(URL, wait_for='a[href^="/evenement/"]', scroll=2)
        if not html:
            return
        yield from _parse(html)
