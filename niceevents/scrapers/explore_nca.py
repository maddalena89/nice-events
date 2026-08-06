"""Explore Nice Côte d'Azur — the metropole tourist office.

Covers all ~50 Métropole communes, which is how Beaulieu-sur-Mer, Villefranche,
Èze, Cap-d'Ail, Saint-Jean-Cap-Ferrat and the hinterland villages get in.
Server-rendered and paginated (~61 pages on the full calendar).

NOTE ON COVERAGE: this is the *Métropole*, so Cannes / Antibes / Menton / Grasse
are NOT included — they're separate intercommunalités with their own tourist
offices. Brocabrac covers them for brocantes; for the rest they'd each need
their own scraper. See README "Known gaps".

Listing item shape:
    - 18 July 2026 26 July 2026
      ## [Event title](/en/event/slug/)
      Concert
      Jazz and blues
      * Villefranche-sur-Mer
"""
from __future__ import annotations

import re
from datetime import date
from typing import Iterator, Optional

from selectolax.parser import HTMLParser

from ..models import Event, classify, parse_date
from .base import HttpScraper, register

BASE = "https://www.explorenicecotedazur.com"

FEEDS = [
    ("/en/events/all-events/", 61),
    ("/en/events/exhibition-calendar/", 6),
    ("/en/events/major-events/", 3),
    ("/en/events/sports-events-calendar/", 4),
]

_DATE_PAIR = re.compile(
    r"(\d{1,2}\s+[A-Za-zÀ-ÿ]+(?:\s+\d{4})?)\s+(\d{1,2}\s+[A-Za-zÀ-ÿ]+(?:\s+\d{4})?)?"
)


@register
class ExploreNCA(HttpScraper):
    name = "explore_nca"
    label = "Explore Nice Côte d'Azur"
    delay = 1.2
    #: hard cap so a pagination bug can't spider the whole site
    MAX_PAGES = 61

    def fetch(self) -> Iterator[Event]:
        seen: set[str] = set()
        for path, pages in FEEDS:
            for page in range(1, min(pages, self.MAX_PAGES) + 1):
                url = f"{BASE}{path}" if page == 1 else f"{BASE}{path}page/{page}/"
                r = self.get(url)
                if not r:
                    break
                found = 0
                for ev in self._parse(r.text):
                    found += 1
                    if ev.fingerprint in seen:
                        continue
                    seen.add(ev.fingerprint)
                    yield ev
                if found == 0:
                    break  # ran past the last page

    def _parse(self, html: str) -> Iterator[Event]:
        tree = HTMLParser(html)
        today = date.today()
        seen: set[str] = set()

        # The card is split into sibling "content-row" divs — one for the date,
        # one for the title (which holds the <a>), one for the town/meta. So the
        # nearest div above the link contains only the title, no date: earlier
        # versions selected that shallow div, found no date, and dropped every
        # card (12 links matched, 0 parsed). Climb from each link until the
        # container's text actually carries BOTH a date and a known town — that
        # is the real card, whatever its class names happen to be.
        for link in tree.css("a[href*='/event/']"):
            href = link.attributes.get("href", "")
            if not href:
                continue

            node = link.parent
            block = ""
            for _ in range(8):                 # cap the climb; cards are shallow
                if node is None:
                    break
                text = re.sub(r"\s+", " ", node.text() or "").strip()
                if len(text) > 6000:           # too big — we've left the card
                    break
                if _DATE_PAIR.search(text) and _town(text):
                    block = text
                    break
                node = node.parent
            if not block:
                continue

            # The <a> wraps the title text directly ("stretched-link"); fall back
            # to a heading or the image alt if it's an image-only link.
            title = re.sub(r"\s+", " ", link.text() or "").strip()
            if not title and node is not None:
                head = node.css_first("h2, h3, h4")
                title = re.sub(r"\s+", " ", (head.text() if head else "") or "").strip()
                if not title:
                    img = node.css_first("img[alt]")
                    title = (img.attributes.get("alt") or "").strip() if img else ""
            if not title or len(title) < 3:
                continue

            ev = self._event(title, href, block, today)
            if ev and ev.fingerprint not in seen:
                seen.add(ev.fingerprint)
                yield ev

    def _event(self, title: str, href: str, block: str, today: date) -> Optional[Event]:
        m = _DATE_PAIR.search(block)
        if not m:
            return None
        start = parse_date(m[1])
        if not start:
            return None
        end = parse_date(m[2]) if m[2] else None
        if end and end < start:
            end = None
        if (end or start) < today:
            return None

        town = _town(block)
        if not town:
            return None

        # The card lists type/theme labels between the title and the town.
        tail = block.split(title, 1)[-1]
        labels = tail.split(town, 1)[0] if town in tail else tail
        labels = re.sub(r"\s+", " ", labels).strip(" *·-")[:90]

        return Event(
            title=title,
            start=start,
            end=end,
            town=town,
            category=classify(title, labels),
            url=href if href.startswith("http") else BASE + href,
            note=labels or None,
            source=self.name,
        )


# Towns this feed actually uses, longest first so "Saint-Martin-Vésubie" wins
# over a bare "Saint-Martin".
_TOWNS = sorted([
    "Beaulieu-sur-Mer", "Villefranche-sur-Mer", "Saint-Jean-Cap-Ferrat", "Cap-d’Ail",
    "Cap-d'Ail", "Saint-Laurent-du-Var", "Saint-Martin-Vésubie", "Saint-Martin-du-Var",
    "Saint-André-de-la-Roche", "Saint-Dalmas-le-Selvage", "Saint-Étienne-de-Tinée",
    "Saint-Sauveur-sur-Tinée", "Châteauneuf-Villevieille", "Tourrette-Levens",
    "Roquebillière", "La Bollène-Vésubie", "Cagnes-sur-Mer", "Castagniers",
    "Saint-Jeannet", "Saint-Blaise", "La Colmiane", "Valdeblore", "Isola 2000",
    "Aspremont", "Belvédère", "Colomars", "Duranus", "Falicon", "Gattières",
    "Gilette", "Lantosque", "La Gaude", "La Tour", "La Trinité", "Le Broc",
    "Levens", "Rimplas", "Roubion", "Roure", "Tournefort", "Utelle", "Venanson",
    "Bairols", "Bonson", "Carros", "Clans", "Drap", "Ilonse", "Isola", "Marie",
    "Auron", "Vence", "Èze", "Nice",
], key=len, reverse=True)


def _town(block: str) -> Optional[str]:
    for t in _TOWNS:
        if re.search(rf"(?<![\w-]){re.escape(t)}(?![\w-])", block):
            return t
    return None
