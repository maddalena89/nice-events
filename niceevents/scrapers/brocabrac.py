"""Brocabrac — vide-greniers, brocantes, bourses, braderies for the 06.

The single best source for the niche stuff; nothing else comes close.
Server-rendered, so plain HTTP is enough.

Page shape:
    <h2>Samedi</h2><h2>18 Juillet 2026</h2>
    <a href="/06/nice/1025571-brocante-de-la-place-garibaldi">Nice Brocante de la place garibaldi</a>
    06300 - Brocante - Place Garibaldi
Dots (•) indicate size; a bare number is the exhibitor count.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Iterator, Optional

from selectolax.parser import HTMLParser

from ..dom import in_order
from ..models import Event, parse_date
from .base import HttpScraper, register

BASE = "https://brocabrac.fr"

_FR_MONTH_RE = (r"janvier|f[ée]vrier|mars|avril|mai|juin|juillet|ao[ûu]t|"
                r"septembre|octobre|novembre|d[ée]cembre")
_DATE_HEAD = re.compile(rf"^\s*(\d{{1,2}})\s+({_FR_MONTH_RE})\s+(\d{{4}})\s*$", re.I)

# "06300  - Brocante  - Place Garibaldi"
_META = re.compile(r"(\d{5})\s*-\s*([^-\n]+?)(?:\s*-\s*(.+))?$")

_TYPE_MAP = {
    "brocante": "Brocante", "vide-grenier": "Vide-grenier", "vide-greniers": "Vide-grenier",
    "braderie": "Braderie", "bourse de collection": "Bourse de collection",
    "vide-dressing": "Vide-dressing", "vide-maison": "Vide-maison",
    "marche de noel": "Marché de Noël",
}


@register
class Brocabrac(HttpScraper):
    name = "brocabrac"
    label = "Brocabrac (06)"
    delay = 1.5

    #: month slugs to sweep beyond the default listing
    MONTHS = ["janvier", "fevrier", "mars", "avril", "mai", "juin",
              "juillet", "aout", "septembre", "octobre", "novembre", "decembre"]

    def _urls(self) -> list[str]:
        """Default page + the next 4 months, so we see well past the first screen."""
        urls = [f"{BASE}/06/"]
        m = date.today().month
        for i in range(4):
            urls.append(f"{BASE}/06/{self.MONTHS[(m - 1 + i) % 12]}/")
        return urls

    def fetch(self) -> Iterator[Event]:
        seen: set[str] = set()
        for url in self._urls():
            r = self.get(url)
            if not r:
                continue
            for ev in self._parse(r.text):
                if ev.fingerprint in seen:
                    continue
                seen.add(ev.fingerprint)
                yield ev

    def _parse(self, html: str) -> Iterator[Event]:
        tree = HTMLParser(html)
        current: Optional[date] = None
        seen_nodes: set[int] = set()

        # Date headings set the context for the event blocks that FOLLOW them,
        # so this walk MUST be in document order — see niceevents/dom.py.
        # css("h2, h3, li") groups by selector and would date every brocante in
        # the page to the final heading, silently.
        for node in in_order(tree, {"h2", "h3", "article", "li", "div"}):
            text = (node.text() or "").strip()

            if node.tag in ("h2", "h3"):
                m = _DATE_HEAD.match(text)
                if m:
                    current = parse_date(f"{m[1]} {m[2]} {m[3]}")
                continue

            if current is None:
                continue

            link = node.css_first("a[href*='/06/']")
            if link is None:
                continue

            href = link.attributes.get("href", "")
            if not re.search(r"/06/[a-z0-9-]+/\d+-", href):
                continue

            # A <li> and its inner <div> both match; take the tightest block
            # holding this link so we don't emit the same event twice.
            if node.css_first("li a[href*='/06/'], div a[href*='/06/']") is not None \
                    and len(node.css("a[href*='/06/']")) > 1:
                continue
            if id(link) in seen_nodes:
                continue
            seen_nodes.add(id(link))

            ev = self._event(node, link, href, current)
            if ev:
                yield ev

    def _event(self, node, link, href: str, when: date) -> Optional[Event]:
        raw_title = (link.text() or "").strip()
        if not raw_title:
            return None

        block = re.sub(r"\s+", " ", node.text() or "")
        meta = _META.search(block)
        postcode = meta[1] if meta else None
        kind_raw = (meta[2].strip() if meta and meta[2] else "")
        venue = (meta[3].strip() if meta and meta[3] else None)

        # Brocabrac prefixes the town onto the title: "Nice Brocante de la place garibaldi"
        town_slug = re.search(r"/06/([a-z0-9-]+)/", href)
        town = town_slug[1].replace("-", " ").title() if town_slug else ""
        title = raw_title
        if town and raw_title.lower().startswith(town.lower()):
            title = raw_title[len(town):].strip(" -–—")
        title = title or raw_title

        kind = _TYPE_MAP.get(kind_raw.lower().replace("é", "e"), kind_raw or "Vide-grenier")

        size = block.count("•")
        exhibitors = re.search(r"(?<![\d/])(\d{2,3})(?!\d)", block.replace(postcode or "", ""))
        bits = [kind]
        if exhibitors:
            bits.append(f"~{exhibitors[1]} exhibitors")
        elif size:
            bits.append(["small", "medium", "large", "very large"][min(size, 4) - 1])

        return Event(
            title=title,
            start=when,
            town=town,
            venue=venue,
            category="brocante",
            url=href if href.startswith("http") else BASE + href,
            note=" · ".join(bits),
            source=self.name,
        )
