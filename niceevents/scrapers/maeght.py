"""Fondation Maeght — the big art foundation at Saint-Paul-de-Vence.

A flagship 06 venue that was missing far too long. Its site is WordPress +
Elementor + WP Grid Builder: the events grid is injected by JavaScript and the
date is rendered by an Elementor widget that the REST API never exposes. So the
REST shortcut that works for nice.fr does NOT work here — the only reliable
source is the rendered page. Hence a browser scraper.

Verified live against the DOM: /events-2026/ shows ~44 cards, ~39 with a clean
"DD/MM/YYYY HH:MM" in the card markup, each linking to /<slug>/. We read them in
a single render.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Iterator, Optional

from selectolax.parser import HTMLParser

from ..models import Event, classify, parse_date, parse_time
from .base import BrowserScraper, register

URL = "https://www.fondation-maeght.com/events-2026/"

_DATE = re.compile(r"(\d{1,2}/\d{1,2}/20\d\d)(?:\s*(\d{1,2}:\d{2}))?")
_EVENT_HREF = re.compile(r"fondation-maeght\.com/[a-z0-9-]+/?$", re.I)


@register
class Maeght(BrowserScraper):
    name = "maeght"
    label = "Fondation Maeght"

    def fetch(self) -> Iterator[Event]:
        html = self._page_text(URL, wait_for=".wpgb-card", scroll=2)
        if not html:
            return
        yield from self._parse(html)

    def _parse(self, html: str) -> Iterator[Event]:
        tree = HTMLParser(html)
        seen: set[str] = set()
        for card in tree.css(".wpgb-card"):
            chtml = card.html or ""
            m = _DATE.search(chtml)
            if not m:
                continue                       # recurring workshops with no fixed date
            start = parse_date(m[1])           # DD/MM/YYYY -> European day-first
            if not start:
                continue

            href = ""
            for a in card.css("a"):
                h = a.attributes.get("href") or ""
                if _EVENT_HREF.search(h) and "events-2026" not in h and "/produit/" not in h:
                    href = h
                    break
            if href in seen:
                continue
            seen.add(href)

            title = ""
            h = card.css_first("h1, h2, h3, h4, h5")
            if h:
                title = re.sub(r"\s+", " ", h.text() or "").strip()
            if not title and href:
                slug = re.search(r"com/([a-z0-9-]+)/?$", href)
                if slug:
                    title = slug[1].replace("-", " ").capitalize()
            if not title:
                continue

            yield Event(
                title=title,
                start=start,
                time=parse_time(m[2]) if m[2] else None,
                town="Saint-Paul-de-Vence",
                venue="Fondation Maeght",
                category=classify(title),
                url=href or URL,
                source=self.name,
            )
