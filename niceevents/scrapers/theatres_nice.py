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

The Alphabet is mostly a children's theatre and we do not list its "jeune public"
shows — see the note on JEUNE_PUBLIC_URL below for how they are told apart.
"""
from __future__ import annotations

import logging
import re
from datetime import date
from typing import Iterator, Optional

from selectolax.parser import HTMLParser

from ..models import Event, parse_date
from .base import BrowserScraper, register

log = logging.getLogger(__name__)

BASE = "https://theatres.nice.fr"
URL = f"{BASE}/les-evenements"

#: The listing card carries venue, genre, title and date but NOT the audience,
#: and genre cannot stand in for it: "C'est pas juste" and "Réveillon à la
#: morgue" are both "Comédie / Café-théâtre / Boulevard", yet only the first is
#: jeune public. So we ask the portal's own search instead, which filters on the
#: real label. The ids come from the <select>s on /recherche:
#:     lieu=7    Alphabet (Théâtre l')
#:     cible=1   Jeune public
#: To re-derive them if the portal ever renumbers, open
#: https://theatres.nice.fr/recherche and read the options of the "lieu" and
#: "cible" selects.
ALPHABET_LIEU = "7"
JEUNE_PUBLIC_CIBLE = "1"
JEUNE_PUBLIC_URL = f"{BASE}/recherche?lieu={ALPHABET_LIEU}&cible={JEUNE_PUBLIC_CIBLE}"

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


def _href(a) -> str:
    """The card's event path, normalised so the listing and the search agree."""
    return (a.attributes.get("href") or "").split("?")[0].rstrip("/")


def _is_alphabet(venue: Optional[str]) -> bool:
    return "alphabet" in (venue or "").lower()


def _cards(html: str):
    """Real event cards. A card without .info-container is the image-only
    duplicate link the portal prints beside every entry."""
    tree = HTMLParser(html)
    for a in tree.css('a[href^="/evenement/"]'):
        if a.css_first(".info-container") and _href(a):
            yield a


def _jeune_public_hrefs(html: str) -> set[str]:
    """Event paths on a rendered /recherche?cible=1 page."""
    return {_href(a) for a in _cards(html)}


def _parse(html: str, jeune_public: Optional[set[str]]) -> Iterator[Event]:
    """Turn the listing into events.

    `jeune_public` is the set of Alphabet children's shows to leave out. Pass
    None to mean "the audience list could not be read": we then drop every
    Alphabet event rather than guess, because letting a children's show back
    onto the site is the failure we are trying to prevent. An empty set is the
    opposite and perfectly normal — the Alphabet simply has none on right now.

    The argument has no default on purpose. Forgetting it should be an instant
    TypeError, not a silent run that quietly loses the whole venue.
    """
    seen: set[str] = set()
    for a in _cards(html):
        href = _href(a)
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

        if _is_alphabet(venue) and (jeune_public is None or href in jeune_public):
            continue                              # children's show, not for us

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
        yield from _parse(html, self._jeune_public())

    def _jeune_public(self) -> Optional[set[str]]:
        """Which Alphabet shows the portal labels "Jeune public".

        Returns None when the page would not render, which the parser reads as
        "cannot tell them apart", not as "there are none".
        """
        page = self._page_text(JEUNE_PUBLIC_URL, wait_for='a[href^="/evenement/"]')
        if not page:
            log.warning("%s: jeune public list would not render — skipping every "
                        "Alphabet event this run", self.name)
            return None
        found = _jeune_public_hrefs(page)
        log.info("%s: skipping %d jeune public show(s) at the Alphabet",
                 self.name, len(found))
        return found
